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

RM_STORE = "Stores - L"
FG_STORE = "Finished Goods - L"
WIP_WAREHOUSE = "Line-1 WIP - L"
COMPANY = "Lumirise"


class MaterialPlanning(Document):
	def on_submit(self):
		"""Post: create the Production Orders (Work Orders) + the consolidated Indent."""
		wo_names = []
		for fg in self.fg_plan:
			if flt(fg.required_qty) <= 0:
				continue
			wo = frappe.get_doc({
				"doctype": "Work Order",
				"production_item": fg.fg_item,
				"bom_no": fg.bom or frappe.db.get_value("Item", fg.fg_item, "default_bom"),
				"qty": flt(fg.required_qty),
				"company": COMPANY,
				"use_multi_level_bom": 0,  # consume the stocked MCPCB sub-assembly directly
				"sales_order": fg.sales_order,
				"fg_warehouse": FG_STORE,
				"wip_warehouse": WIP_WAREHOUSE,
				"source_warehouse": RM_STORE,
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
			"branch": self.branch or COMPANY,
			"indent_type": "Purchase",
			"source_planning": self.name,
			"source_sales_order": self.fg_plan[0].sales_order if self.fg_plan else None,
			"items": [{
				"item_code": item, "qty": d["qty"], "uom": "Nos",
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


def _pending_po(item):
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
	rows = frappe.db.sql(
		"""SELECT COALESCE(SUM(i.approved_qty),0) FROM `tabVendor PDI Item` i
		   JOIN `tabVendor PDI` p ON p.name=i.parent
		   WHERE i.item_code=%(item)s AND p.docstatus=1""", {"item": item})
	return flt(rows[0][0]) if rows else 0


def _pending_iqc(item):
	rows = frappe.db.sql(
		"""SELECT COALESCE(SUM(i.accepted_qty),0) FROM `tabIQC Item` i
		   JOIN `tabIQC` p ON p.name=i.parent
		   WHERE i.item_code=%(item)s AND p.docstatus=1""", {"item": item})
	return flt(rows[0][0]) if rows else 0


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

	fg_plan, components = [], []
	for so in sales_orders:
		so_doc = frappe.get_doc("Sales Order", so)
		for soi in so_doc.items:
			bom = frappe.db.get_value("Item", soi.item_code, "default_bom")
			if not bom:
				continue
			fg_available = _stock(soi.item_code, FG_STORE)
			required = max(0, flt(soi.qty) - fg_available)
			fg_plan.append({
				"sales_order": so, "fg_item": soi.item_code, "bom": bom,
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
				rm_avail = _stock(comp, RM_STORE)
				blocked = _blocked_for_other_so(comp, exclude)
				usable = max(0, rm_avail - blocked)
				to_order = max(0, comp_required - usable)
				components.append({
					"sales_order": so, "fg_item": soi.item_code, "component_item": comp,
					"required_qty": comp_required, "rm_available": rm_avail,
					"blocked_for_other_so": blocked,
					"available_after_blocking": usable,
					"pending_po": _pending_po(comp), "pending_pdi": _pending_pdi(comp),
					"pending_iqc": _pending_iqc(comp), "indent_balance": _indent_balance(comp),
					"to_be_ordered": to_order,
				})
	return {"fg_plan": fg_plan, "components": components}
