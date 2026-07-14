"""Lumirise Production Plan report.

Same-as-the-sheet view of the client's monthly "July Sales" tab, but sourced live
from the Lumirise Production Schedule instead of a hand-typed Excel: one row per FG
slice with the exact columns they use —

  Production Date | Delivery Date | Category | SO No | MR No | Item Name |
  Production Qty | Remark | CPH | LINES

plus the values ERP gives for free that their sheet leaves blank (Line, Priority,
Urgent, Schedule ref). LINES = Production Qty / CPH (their capacity math). Reads the
Production Schedule Line rows so the report and the planner never disagree.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions, values = _conditions(filters)

	rows = frappe.db.sql(
		f"""
		SELECT
			psl.scheduled_date      AS production_date,
			psl.delivery_date       AS delivery_date,
			psl.category            AS category,
			psl.sales_order         AS so_no,
			psl.mr_no               AS mr_no,
			COALESCE(NULLIF(psl.fg_item_name, ''), psl.fg_item) AS item_name,
			psl.fg_item             AS fg_item,
			psl.slice_qty           AS production_qty,
			psl.remark              AS remark,
			psl.cph                 AS cph,
			psl.lines_needed        AS `lines`,
			psl.production_line     AS `line`,
			psl.priority            AS priority,
			psl.urgent_flag         AS urgent,
			psl.material_status     AS material_status,
			ps.name                 AS schedule,
			ps.release_status       AS release_status
		FROM `tabProduction Schedule Line` psl
		INNER JOIN `tabLumirise Production Schedule` ps ON ps.name = psl.parent
		WHERE ps.docstatus < 2 {conditions}
		ORDER BY psl.scheduled_date IS NULL, psl.scheduled_date, psl.priority, psl.sales_order
		""",
		values,
		as_dict=True,
	)

	for r in rows:
		# Recompute LINES defensively so a stale row can never mislead.
		r["lines"] = (flt(r.production_qty) / flt(r.cph)) if flt(r.cph) else flt(r.lines)

	return _columns(), rows


def _conditions(filters):
	conditions, values = "", {}
	if filters.get("schedule"):
		conditions += " AND ps.name = %(schedule)s"
		values["schedule"] = filters.schedule
	if filters.get("from_date"):
		conditions += " AND psl.scheduled_date >= %(from_date)s"
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions += " AND psl.scheduled_date <= %(to_date)s"
		values["to_date"] = filters.to_date
	if filters.get("category"):
		conditions += " AND psl.category = %(category)s"
		values["category"] = filters.category
	if filters.get("sales_order"):
		conditions += " AND psl.sales_order = %(sales_order)s"
		values["sales_order"] = filters.sales_order
	if filters.get("only_released"):
		conditions += " AND ps.release_status = 'Released'"
	return conditions, values


def _columns():
	return [
		{"label": _("Production Date"), "fieldname": "production_date", "fieldtype": "Date", "width": 115},
		{"label": _("Delivery Date"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 110},
		{"label": _("Category"), "fieldname": "category", "fieldtype": "Data", "width": 150},
		{"label": _("SO No"), "fieldname": "so_no", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("MR No"), "fieldname": "mr_no", "fieldtype": "Data", "width": 120},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 260},
		{"label": _("Production Qty"), "fieldname": "production_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Remark"), "fieldname": "remark", "fieldtype": "Data", "width": 200},
		{"label": _("CPH"), "fieldname": "cph", "fieldtype": "Float", "width": 90},
		{"label": _("LINES"), "fieldname": "lines", "fieldtype": "Float", "width": 90, "precision": 2},
		{"label": _("Line"), "fieldname": "line", "fieldtype": "Link", "options": "Warehouse", "width": 110},
		{"label": _("Priority"), "fieldname": "priority", "fieldtype": "Int", "width": 75},
		{"label": _("Urgent"), "fieldname": "urgent", "fieldtype": "Check", "width": 65},
		{"label": _("Material Status"), "fieldname": "material_status", "fieldtype": "Data", "width": 240},
		{"label": _("Schedule"), "fieldname": "schedule", "fieldtype": "Link", "options": "Lumirise Production Schedule", "width": 130},
	]
