# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Material Planning = the Focus 9 "Integration / Planning" cockpit.
#   - "Get Sales Orders"  -> compute_plan(): explode BOM, compute the
#     reservation/blocking columns (available, blocked-for-other-SOs,
#     available-after-blocking, pending PO/PDI/IQC, indent-balance, to-be-ordered).
#   - "Post" (submit)     -> create a Work Order per FG + ONE consolidated Indent
#     for the positive to-be-ordered lines. This is the single action the client
#     knows: Post -> Production Order + Indent.

import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt, nowdate, add_days

from lumirise_custom import defaults as config


class MaterialPlanning(Document):
	def on_submit(self):
		"""Post: create the Production Orders (Work Orders) + the consolidated Indent."""
		company = config.get_company(self)
		fg_wh, wip_wh, rm_wh = config.fg_warehouse(), config.wip_warehouse(), config.rm_warehouse()
		wo_names = []
		for fg in self.fg_plan:
			if flt(fg.required_qty) <= 0:
				continue
			wo = frappe.get_doc({
				"doctype": "Work Order",
				"production_item": fg.fg_item,
				"bom_no": fg.bom or frappe.db.get_value("Item", fg.fg_item, "default_bom"),
				"qty": flt(fg.required_qty),
				"company": company,
				"use_multi_level_bom": 0,  # consume the stocked MCPCB sub-assembly directly
				"sales_order": fg.sales_order,
				"fg_warehouse": fg_wh,
				"wip_warehouse": wip_wh,
				"source_warehouse": rm_wh,
				"lr_source_planning": self.name,
			})
			wo.insert(ignore_permissions=True)
			wo.submit()
			wo_names.append(wo.name)

		indent_name = self._create_consolidated_indent()

		self.db_set("created_work_orders", ", ".join(wo_names))
		if indent_name:
			self.db_set("created_indent", indent_name)

		msg = f"Posted: {len(wo_names)} Production Order(s)"
		if indent_name:
			msg += f" + Indent {indent_name}"
		frappe.msgprint(msg, indicator="green", alert=True)

	def _create_consolidated_indent(self):
		# aggregate the positive to-be-ordered lines (common parts summed)
		agg = {}
		for c in self.components:
			if flt(c.to_be_ordered) <= 0:
				continue
			row = agg.setdefault(c.component_item, {"qty": 0, "model": c.fg_item, "so": c.sales_order})
			row["qty"] += flt(c.to_be_ordered)
		if not agg:
			return None
		indent = frappe.get_doc({
			"doctype": "Indent",
			"indent_date": nowdate(),
			"branch": self.branch or config.get_company(self),
			"indent_type": "Purchase",
			"source_planning": self.name,
			"source_sales_order": self.fg_plan[0].sales_order if self.fg_plan else None,
			"items": [{
				"item_code": item, "qty": d["qty"], "uom": config.item_uom(item),
				"required_date": add_days(nowdate(), 15),
				"source_bom": frappe.db.get_value("Item", d["model"], "default_bom"),
				"model": d["model"], "for_sales_order": d["so"],
			} for item, d in agg.items()],
		})
		indent.insert(ignore_permissions=True)
		return indent.name

	def on_cancel(self):
		"""Best-effort rollback so the demo can be re-filmed."""
		for wo in (self.created_work_orders or "").split(", "):
			wo = wo.strip()
			if wo and frappe.db.exists("Work Order", wo):
				doc = frappe.get_doc("Work Order", wo)
				if doc.docstatus == 1:
					try:
						doc.cancel()
					except Exception:
						pass
		if self.created_indent and frappe.db.exists("Indent", self.created_indent):
			ind = frappe.get_doc("Indent", self.created_indent)
			if ind.docstatus == 0:
				frappe.delete_doc("Indent", self.created_indent, force=True)


# --------------------------------------------------------------------- helpers
def _stock(item, warehouse):
	return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "actual_qty"))


def _blocked_for_other_so(item, exclude_sos):
	"""Reserved by submitted, not-completed Work Orders for OTHER sales orders."""
	rows = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(woi.required_qty - woi.consumed_qty), 0)
		FROM `tabWork Order Item` woi
		JOIN `tabWork Order` wo ON wo.name = woi.parent
		WHERE woi.item_code = %(item)s
		  AND wo.docstatus = 1
		  AND wo.status NOT IN ('Completed', 'Stopped')
		  AND COALESCE(wo.sales_order, '') NOT IN %(sos)s
		""",
		{"item": item, "sos": tuple(exclude_sos) or ("",)},
	)
	return flt(rows[0][0]) if rows else 0


# --- Inbound pipeline buckets (single source of truth, no double-count) --------
# The open PO qty is the anchor. As a qty advances PO -> Vendor PDI -> Logistics ->
# IQC -> GRN, it is counted at exactly ONE stage (its FURTHEST live document), so
#   Pending PO + Pending PDI + In Transit + Pending IQC == OPEN  (always).
# A qty rejected at any stage simply never advances, so it falls back into the
# Pending PO residual = OPEN − (Pending PDI + In Transit + Pending IQC).


def _open_po(item):
	"""OPEN = qty still owed by vendors (on a submitted, non-closed PO, not GRN'd)."""
	rows = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(poi.qty - poi.received_qty), 0)
		FROM `tabPurchase Order Item` poi
		JOIN `tabPurchase Order` po ON po.name = poi.parent
		WHERE poi.item_code = %(item)s AND po.docstatus = 1 AND po.status != 'Closed'
		""",
		{"item": item},
	)
	return flt(rows[0][0]) if rows else 0


def _pending_pdi(item):
	"""Vendor PDI approved qty that is NOT yet handed to an Inbound Logistics doc."""
	rows = frappe.db.sql(
		"""SELECT COALESCE(SUM(i.approved_qty),0) FROM `tabVendor PDI Item` i
		   JOIN `tabVendor PDI` p ON p.name=i.parent
		   WHERE i.item_code=%(item)s AND p.docstatus < 2
		     AND NOT EXISTS (SELECT 1 FROM `tabInbound Logistics` l
		                     WHERE l.vendor_pdi = p.name AND l.docstatus < 2)""",
		{"item": item})
	return flt(rows[0][0]) if rows else 0


def _in_transit(item):
	"""Qty dispatched / on-the-water: in a Logistics doc (Dispatched or In Transit)
	that has NOT yet been handed to an IQC."""
	rows = frappe.db.sql(
		"""SELECT COALESCE(SUM(i.qty),0) FROM `tabInbound Logistics Item` i
		   JOIN `tabInbound Logistics` l ON l.name=i.parent
		   WHERE i.item_code=%(item)s AND l.docstatus < 2
		     AND COALESCE(l.status,'') IN ('Dispatched','In Transit')
		     AND NOT EXISTS (SELECT 1 FROM `tabIQC` q
		                     WHERE q.inbound_logistics = l.name AND q.docstatus < 2)""",
		{"item": item})
	return flt(rows[0][0]) if rows else 0


def _pending_iqc(item):
	"""Reached the warehouse but not yet GRN'd:
	 (A) Logistics 'Reached Warehouse' with no IQC raised yet, plus
	 (B) IQC accepted qty not yet moved to RM (GRN posted)."""
	a = frappe.db.sql(
		"""SELECT COALESCE(SUM(i.qty),0) FROM `tabInbound Logistics Item` i
		   JOIN `tabInbound Logistics` l ON l.name=i.parent
		   WHERE i.item_code=%(item)s AND l.docstatus < 2
		     AND COALESCE(l.status,'') = 'Reached Warehouse'
		     AND NOT EXISTS (SELECT 1 FROM `tabIQC` q
		                     WHERE q.inbound_logistics = l.name AND q.docstatus < 2)""",
		{"item": item})
	b = frappe.db.sql(
		"""SELECT COALESCE(SUM(i.accepted_qty),0) FROM `tabIQC Item` i
		   JOIN `tabIQC` q ON q.name=i.parent
		   WHERE i.item_code=%(item)s AND q.docstatus < 2
		     AND COALESCE(q.status,'') != 'Moved to RM'""",
		{"item": item})
	return (flt(a[0][0]) if a else 0) + (flt(b[0][0]) if b else 0)


def _indent_balance(item):
	"""Qty already on a submitted Indent but not yet converted to a PO."""
	rows = frappe.db.sql(
		"""SELECT COALESCE(SUM(i.qty),0) FROM `tabIndent Item` i
		   JOIN `tabIndent` p ON p.name=i.parent
		   WHERE i.item_code=%(item)s AND p.docstatus=1
		     AND COALESCE(p.workflow_state,'') != 'Ordered'""", {"item": item})
	return flt(rows[0][0]) if rows else 0


@frappe.whitelist()
def compute_plan(sales_orders):
	"""Explode the chosen Sales Orders and compute the planning grid.
	Returns {fg_plan: [...], components: [...]} for the client to populate."""
	if isinstance(sales_orders, str):
		sales_orders = json.loads(sales_orders)
	exclude = list(sales_orders)

	fg_wh, rm_wh = config.fg_warehouse(), config.rm_warehouse()
	fg_plan, components = [], []
	for so in sales_orders:
		so_doc = frappe.get_doc("Sales Order", so)
		for soi in so_doc.items:
			bom = frappe.db.get_value("Item", soi.item_code, "default_bom")
			if not bom:
				continue
			fg_available = _stock(soi.item_code, fg_wh)
			required = max(0, flt(soi.qty) - fg_available)
			fg_plan.append({
				"sales_order": so, "fg_item": soi.item_code,
				"fg_item_name": soi.item_name, "bom": bom,
				"aso_qty": flt(soi.qty), "fg_available": fg_available,
				"required_qty": required,
			})
			if required <= 0:
				continue
			bom_doc = frappe.get_doc("BOM", bom)
			per = flt(bom_doc.quantity) or 1
			for bi in bom_doc.items:
				comp = bi.item_code
				comp_required = flt(bi.qty) / per * required
				rm_avail = _stock(comp, rm_wh)
				blocked = _blocked_for_other_so(comp, exclude)
				usable = max(0, rm_avail - blocked)

				# Live inbound pipeline, each qty in exactly one bucket.
				open_po = _open_po(comp)            # total still owed by vendors
				p = _pending_pdi(comp)              # at Vendor PDI, not dispatched
				t = _in_transit(comp)               # dispatched / in transit
				r = _pending_iqc(comp)              # reached, IQC not passed/GRN'd
				pending_po = max(0, open_po - (p + t + r))  # residual = not started
				indent_bal = _indent_balance(comp)  # on indent, not yet PO'd

				# Net the WHOLE incoming pipeline (open PO + indent) so Planning never
				# re-orders qty already on its way in.
				to_order = max(0, comp_required - usable - open_po - indent_bal)

				components.append({
					"sales_order": so, "fg_item": soi.item_code, "component_item": comp,
					"component_item_name": bi.item_name,
					"required_qty": comp_required, "rm_available": rm_avail,
					"blocked_for_other_so": blocked,
					"available_after_blocking": usable,
					"pending_po": pending_po, "pending_pdi": p, "in_transit": t,
					"pending_iqc": r, "indent_balance": indent_bal,
					"to_be_ordered": to_order,
				})
	return {"fg_plan": fg_plan, "components": components}
