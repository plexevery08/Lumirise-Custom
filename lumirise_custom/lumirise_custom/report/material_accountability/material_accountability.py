# Material Accountability — the "requested vs issued vs balance" view the client
# asked for ("if the order is 10,000, I should see how many I gave and what's
# remaining"). Per Work Order: Required → Issued to line → Produced → Balances,
# plus the per-line split of what was transferred (each line is its own warehouse).

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 140},
		{"label": _("FG Item"), "fieldname": "production_item", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 130},
		{"label": _("Required"), "fieldname": "required", "fieldtype": "Float", "width": 90},
		{"label": _("Issued to Line"), "fieldname": "issued", "fieldtype": "Float", "width": 110},
		{"label": _("Bal. to Issue"), "fieldname": "bal_issue", "fieldtype": "Float", "width": 100},
		{"label": _("Produced"), "fieldname": "produced", "fieldtype": "Float", "width": 90},
		{"label": _("Bal. to Produce"), "fieldname": "bal_produce", "fieldtype": "Float", "width": 110},
		{"label": _("Per-line Issued"), "fieldname": "per_line", "fieldtype": "Data", "width": 260},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	conditions = {"docstatus": 1}
	if filters.get("company"):
		conditions["company"] = filters["company"]
	if filters.get("work_order"):
		conditions["name"] = filters["work_order"]
	if filters.get("production_item"):
		conditions["production_item"] = filters["production_item"]
	if filters.get("sales_order"):
		conditions["sales_order"] = filters["sales_order"]
	if not filters.get("include_completed"):
		conditions["status"] = ["not in", ["Completed", "Stopped", "Closed"]]

	work_orders = frappe.get_all(
		"Work Order",
		filters=conditions,
		fields=[
			"name", "production_item", "sales_order", "status", "qty",
			"material_transferred_for_manufacturing", "produced_qty",
		],
		order_by="creation desc",
	)

	data = []
	for wo in work_orders:
		required = flt(wo.qty)
		issued = flt(wo.material_transferred_for_manufacturing)
		produced = flt(wo.produced_qty)
		data.append({
			"work_order": wo.name,
			"production_item": wo.production_item,
			"sales_order": wo.sales_order,
			"required": required,
			"issued": issued,
			"bal_issue": required - issued,
			"produced": produced,
			"bal_produce": required - produced,
			"per_line": _per_line_issued(wo.name),
			"status": wo.status,
		})
	return data


def _per_line_issued(work_order):
	"""Qty transferred to each line warehouse for this Work Order (the kit transfer
	carries fg_completed_qty = the order qty moved to that line)."""
	rows = frappe.get_all(
		"Stock Entry",
		filters={
			"work_order": work_order,
			"docstatus": 1,
			"purpose": "Material Transfer for Manufacture",
		},
		fields=["to_warehouse", "fg_completed_qty"],
	)
	by_line = {}
	for r in rows:
		if not r.to_warehouse:
			continue
		by_line[r.to_warehouse] = by_line.get(r.to_warehouse, 0) + flt(r.fg_completed_qty)
	return ", ".join(f"{wh}: {flt(qty):g}" for wh, qty in sorted(by_line.items())) or "—"
