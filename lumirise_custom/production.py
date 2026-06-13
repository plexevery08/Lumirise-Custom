"""Production execution — line-aware, one-click drivers over the native Work Order
flow that mirror the Focus 9 screen sequence while keeping standard ERPNext stock
mechanics (and its Required → Transferred → Produced → Consumed accountability)
underneath.

The Focus screens, in order, and the helper that drives each:

  Material Issue to Shop Floor   -> issue_to_shop_floor   RM Store  -> Shop Floor
  Internal Stock Transfer to Line-> transfer_to_line      Shop Floor-> Line-N (WIP)
  Receipt from Production        -> receive_finished_goods Line-N    -> Production FG
  Rejection from Production      -> reject_from_line       Prod FG   -> RM Rejection (draft)
  FG to Dispatch Transfer        -> move_to_dispatch       Prod FG   -> Dispatch FG

Each line is its own Warehouse (Lumirise Operations Settings → Production Lines), so
per-line stock is visible and RM is consumed from the exact line it was transferred
to. We set Manufacturing Settings.backflush_raw_materials_based_on = "Material
Transferred for Manufacture" in setup so a Manufacture entry pulls RM from whichever
line it was transferred into.

KEY: native Work Order qty accounting is warehouse-agnostic — it keys on
work_order + purpose + fg_completed_qty + is_finished_item, never on the warehouse —
so overriding warehouses to a specific line is safe. We NEVER mutate wo.wip_warehouse
(it backs stock reservations and available-qty). Costing auto-sync
(costing.on_stock_entry) and the SO production-status sync fire off the resulting
stock entries automatically; the task engine raises the next team's card off the
Stock Entry Type.
"""

import frappe
from frappe import _
from frappe.utils import flt

from lumirise_custom import defaults as config


def _get_submitted_wo(work_order):
	wo = frappe.get_doc("Work Order", work_order)
	if wo.docstatus != 1:
		frappe.throw(_("Work Order {0} must be submitted before production.").format(work_order))
	return wo


def _validate_line(line_warehouse):
	"""line_warehouse must be one of the configured production lines."""
	if not line_warehouse:
		frappe.throw(_("Select a production line."))
	if not config.is_valid_line(line_warehouse):
		frappe.throw(
			_("{0} is not a configured production line. Add it under Lumirise "
			  "Operations Settings → Production Lines.").format(line_warehouse))


def _native_se_dict(work_order, purpose, qty=None):
	"""Native Work Order stock entry as a plain dict (not yet inserted)."""
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	if qty is not None:
		return make_stock_entry(work_order, purpose, qty=qty)
	return make_stock_entry(work_order, purpose)


def _submit_se(se_dict, stock_entry_type, customise=None):
	"""Build, customise, insert and submit a Stock Entry. `stock_entry_type` is the
	Focus-named custom type (purpose is inferred from it / already set by native
	make_stock_entry). `customise(se)` may mutate warehouses/rows before insert."""
	se = frappe.get_doc(se_dict) if isinstance(se_dict, dict) else se_dict
	se.stock_entry_type = stock_entry_type
	if customise:
		customise(se)
	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)
	se.submit()
	return se


@frappe.whitelist()
def issue_to_shop_floor(work_order, qty=None):
	"""Focus 'Material Issue to Shop Floor': move the BOM kit RM Store → Shop Floor
	for the given (partial) qty. This is staging only — it does NOT bump the Work
	Order's transferred-for-manufacture (that happens when material reaches a line),
	so the WO balance still reflects what is actually on the lines."""
	frappe.has_permission("Work Order", "write", work_order, throw=True)
	wo = _get_submitted_wo(work_order)
	qty = flt(qty) if qty not in (None, "") else (flt(wo.qty) - flt(wo.material_transferred_for_manufacturing))
	if qty <= 0:
		frappe.throw(_("Nothing left to issue for this Work Order."))

	rm_wh = config.rm_warehouse()
	floor_wh = config.shop_floor_warehouse()

	# Use the native helper to compute the correct component rows/qty, then recast
	# it as a plain RM Store -> Shop Floor transfer (drop the WO/BOM links so it
	# stays inert for WO qty accounting — pure staging).
	se_dict = _native_se_dict(work_order, "Material Transfer for Manufacture", qty=qty)
	se_dict["purpose"] = "Material Transfer"
	se_dict["from_warehouse"] = rm_wh
	se_dict["to_warehouse"] = floor_wh
	se_dict["work_order"] = None
	se_dict["bom_no"] = None
	se_dict["from_bom"] = 0
	se_dict["fg_completed_qty"] = 0
	se_dict["custom_narration"] = f"Issue to shop floor for WO {work_order}"
	for row in se_dict.get("items", []):
		row["s_warehouse"] = rm_wh
		row["t_warehouse"] = floor_wh

	se = _submit_se(se_dict, "Material Issue to Shop Floor")
	return {"stock_entry": se.name, "shop_floor": floor_wh, "qty": qty}


@frappe.whitelist()
def transfer_to_line(work_order, line_warehouse, qty):
	"""Focus 'Internal Stock Transfer to Line': move the kit Shop Floor → the chosen
	line (native Material Transfer for Manufacture, so WO.transferred increments).
	Supports splitting one Work Order across several lines."""
	frappe.has_permission("Work Order", "write", work_order, throw=True)
	wo = _get_submitted_wo(work_order)
	_validate_line(line_warehouse)
	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Transfer qty must be greater than zero."))
	pending = flt(wo.qty) - flt(wo.material_transferred_for_manufacturing)
	if qty > pending + 0.001:
		frappe.throw(_("Transfer qty {0} exceeds the pending qty {1} to transfer on this Work Order.").format(qty, pending))

	floor_wh = config.shop_floor_warehouse()

	def _to_line(se):
		se.from_warehouse = floor_wh
		se.to_warehouse = line_warehouse
		se.custom_narration = f"{line_warehouse}"
		for row in se.items:
			row.s_warehouse = floor_wh
			row.t_warehouse = line_warehouse

	se_dict = _native_se_dict(work_order, "Material Transfer for Manufacture", qty=qty)
	se = _submit_se(se_dict, "Internal Stock Transfer to Line", customise=_to_line)
	return {"stock_entry": se.name, "line_warehouse": line_warehouse, "qty": qty}


@frappe.whitelist()
def receive_finished_goods(work_order, line_warehouse, produced_qty, physical_qty=None):
	"""Focus 'Receipt from Production': post finished goods (native Manufacture) for
	the chosen line — consumes RM from that line, produces into the Production FG
	store. If a physical box count is supplied and differs from the system qty, raise
	a Stock-Mismatch task instead of letting the gap pass silently."""
	frappe.has_permission("Work Order", "write", work_order, throw=True)
	wo = _get_submitted_wo(work_order)
	_validate_line(line_warehouse)
	produced_qty = flt(produced_qty)
	if produced_qty <= 0:
		frappe.throw(_("Produced qty must be greater than zero."))
	pending = flt(wo.qty) - flt(wo.produced_qty)
	if produced_qty > pending + 0.001:
		frappe.throw(_("Produced qty {0} exceeds the pending qty {1} on this Work Order.").format(produced_qty, pending))

	prod_fg = config.production_fg_warehouse()

	def _from_line(se):
		se.to_warehouse = prod_fg
		se.custom_narration = f"Built on {line_warehouse}"
		for row in se.items:
			if getattr(row, "is_finished_item", 0):
				row.t_warehouse = prod_fg
			elif row.s_warehouse:
				# Consume the raw materials from the specific line they were
				# transferred to (backflush mode already points here; pin it
				# explicitly so a multi-line WO consumes from the right line).
				# Scrap rows have no s_warehouse, so they are left untouched.
				row.s_warehouse = line_warehouse

	se_dict = _native_se_dict(work_order, "Manufacture", qty=produced_qty)
	se = _submit_se(se_dict, "Receipt from Production", customise=_from_line)

	mismatch = physical_qty not in (None, "") and flt(physical_qty) != produced_qty
	if mismatch:
		from lumirise_custom.task_engine import create_task

		create_task(
			title=f"FG count mismatch on WO {work_order}",
			department="FG Stores - Dispatch",
			task_type="Stock Mismatch",
			priority="High",
			reference_doctype="Work Order",
			reference_name=work_order,
			description=(
				f"System recorded {produced_qty} produced on {wo.production_item} "
				f"({line_warehouse}), but FG physically counted {flt(physical_qty)}. "
				f"Reconcile the box count before accepting the lot."
			),
			source_event="fg_mismatch",
			dedup=False,
		)
	return {"stock_entry": se.name, "produced_qty": produced_qty, "line_warehouse": line_warehouse, "mismatch": bool(mismatch)}


@frappe.whitelist()
def reject_from_line(work_order, qty, line_warehouse=None, reason=None):
	"""Focus 'Rejection from Production': Quality-gated rejection of received finished
	goods that failed at the line. Creates a DRAFT Material Transfer of the rejected
	qty from the Production FG store to the RM Rejection store and a Defect task to
	Quality — stock is NOT posted until Quality reviews and submits it.

	(We pull from Production FG, where the produced units actually live, to keep stock
	honest; the line is recorded on the entry for traceability.)"""
	frappe.has_permission("Work Order", "write", work_order, throw=True)
	wo = _get_submitted_wo(work_order)
	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Rejection qty must be greater than zero."))

	rejection_wh = config.rejection_warehouse(required=False) or wo.scrap_warehouse
	if not rejection_wh:
		frappe.throw(_("Set a Rejection Store in Lumirise Operations Settings (or a Scrap Warehouse on the Work Order)."))
	prod_fg = config.production_fg_warehouse()
	line_note = f" ({line_warehouse})" if line_warehouse else ""

	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"company": wo.company,
			"from_warehouse": prod_fg,
			"to_warehouse": rejection_wh,
			"custom_narration": f"Rejected from production{line_note}",
			"remarks": f"Production rejection from WO {work_order}{line_note}: {reason or '—'}",
			"items": [
				{
					"item_code": wo.production_item,
					"qty": qty,
					"s_warehouse": prod_fg,
					"t_warehouse": rejection_wh,
					"allow_zero_valuation_rate": 1,
				}
			],
		}
	)
	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)  # left as DRAFT for Quality to approve + submit

	from lumirise_custom.task_engine import create_task

	create_task(
		title=f"Approve production rejection ({qty}) from WO {work_order}",
		department="Quality - PDI/IQC",
		task_type="Defect / Rejection",
		priority="High",
		reference_doctype="Stock Entry",
		reference_name=se.name,
		description=(
			f"{qty} of {wo.production_item} rejected from production{line_note} "
			f"(Work Order {work_order}). Reason: {reason or '—'}. Review and submit "
			f"the draft transfer to the RM Rejection store, then raise any vendor/"
			f"scrap action."
		),
		source_event="prod_reject",
		dedup=False,
	)
	return {"draft_stock_entry": se.name}


@frappe.whitelist()
def move_to_dispatch(work_order=None, item_code=None, qty=None):
	"""Focus 'FG to Dispatch Transfer': move finished goods Production FG → Dispatch
	FG (plain Material Transfer). Pass a Work Order to default the item + the qty still
	sitting in Production FG, or pass item_code + qty directly."""
	prod_fg = config.production_fg_warehouse()
	dispatch_fg = config.dispatch_fg_warehouse()

	if work_order:
		frappe.has_permission("Work Order", "write", work_order, throw=True)
		wo = _get_submitted_wo(work_order)
		item_code = item_code or wo.production_item
		company = wo.company
		if qty in (None, ""):
			qty = _qty_in_warehouse(item_code, prod_fg)
		narration = f"FG to dispatch for WO {work_order}"
	else:
		if not item_code:
			frappe.throw(_("Provide a Work Order or an item to move to Dispatch FG."))
		company = config.get_company()
		narration = f"FG to dispatch — {item_code}"

	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Nothing in the Production FG store to move to Dispatch FG."))

	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "FG to Dispatch Transfer",
			"company": company,
			"from_warehouse": prod_fg,
			"to_warehouse": dispatch_fg,
			"custom_narration": narration,
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"s_warehouse": prod_fg,
					"t_warehouse": dispatch_fg,
				}
			],
		}
	)
	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)
	se.submit()
	return {"stock_entry": se.name, "qty": qty, "dispatch_fg": dispatch_fg}


def _qty_in_warehouse(item_code, warehouse):
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))


@frappe.whitelist()
def get_production_lines():
	"""Configured production-line warehouses, for the Work Order cockpit dropdowns."""
	return config.production_lines()
