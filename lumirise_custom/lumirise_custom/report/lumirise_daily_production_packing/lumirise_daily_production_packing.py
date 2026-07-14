"""Lumirise Daily Production & Packing report.

The ERP twin of the client's weekly-workbook "Day-Mon … Day-Sun" sheets: one row per
Lumirise Job Card (line × product × day) with their exact columns and per-line subtotal
rows, driven straight off the Job Cards the supervisors fill at 5:30 PM. The MD
Dashboard / Weekly Summary rollup lives in the separate "Lumirise MD Production
Dashboard" report; this is the granular sheet under it.

Columns (their sheet):
  Line | Supervisor | Operators | Customer | Product | Carry Fwd | New RM Issued |
  Target (CF+RM) | RM Stock at Line | Assembled on Line | Assembled on Aging |
  Assembled at Packing | FG Packed | Rejection | Rejection Reason |
  Actual (FG) | Balance to Produce (Target-Actual) | Achievement % (FG/Target) | Remarks

Bands (their legend): >=95% green, 80-95% orange, <80% red.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from lumirise_custom import defaults as config

_SUM_FIELDS = (
	"carry_fwd", "new_rm", "target", "rm_at_line", "on_line", "on_aging",
	"at_packing", "fg_packed", "rejection", "actual", "balance",
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.from_date or nowdate())
	to_date = getdate(filters.to_date or from_date)

	conditions = {"production_date": ["between", [from_date, to_date]], "docstatus": ["<", 2]}
	if filters.get("production_line"):
		conditions["production_line"] = filters.production_line
	if filters.get("customer"):
		conditions["customer"] = filters.customer

	cards = frappe.get_all(
		"Lumirise Job Card",
		filters=conditions,
		fields=[
			"name", "production_line", "production_date", "operators", "customer",
			"fg_item", "carry_fwd_qty", "new_rm_issued", "target_qty",
			"qty_on_line", "qty_on_aging", "qty_at_packing", "produced_qty",
			"rejection_qty", "rejection_reason", "remarks",
		],
		order_by="production_line, production_date, name",
		limit_page_length=0,
	)

	# resolve per-line helpers once
	line_wh = sorted({c.production_line for c in cards if c.production_line})
	rm_at_line = {wh: _bin_qty(wh) for wh in line_wh}
	item_name = {}

	data = []
	grand = _zero()
	# cards are ordered by production_line, so we can group in one pass.
	_UNSET = "\x00__no_line__"
	cur_line = _UNSET
	subtotal = _zero()

	def flush_subtotal(line_val):
		if line_val != _UNSET and any(subtotal[f] for f in _SUM_FIELDS):
			row = {"line": f"{config.line_name(line_val)} — TOTAL", "is_subtotal": 1}
			row.update({f: subtotal[f] for f in _SUM_FIELDS})
			row["achievement_pct"] = _pct(subtotal["fg_packed"], subtotal["target"])
			data.append(row)

	for c in cards:
		if c.production_line != cur_line:
			flush_subtotal(cur_line)
			subtotal = _zero()
			cur_line = c.production_line

		if c.fg_item not in item_name:
			item_name[c.fg_item] = frappe.db.get_value("Item", c.fg_item, "item_name") or c.fg_item

		actual = flt(c.produced_qty)  # Weekly-Summary definition: Actual Production = FG Packed
		balance = flt(c.target_qty) - actual
		vals = {
			"job_card": c.name,
			"line": config.line_name(c.production_line),
			"supervisor": config.line_supervisor(c.production_line),
			"operators": c.operators,
			"customer": c.customer,
			"product": item_name[c.fg_item],
			"production_date": c.production_date,
			"carry_fwd": flt(c.carry_fwd_qty),
			"new_rm": flt(c.new_rm_issued),
			"target": flt(c.target_qty),
			"rm_at_line": rm_at_line.get(c.production_line, 0),
			"on_line": flt(c.qty_on_line),
			"on_aging": flt(c.qty_on_aging),
			"at_packing": flt(c.qty_at_packing),
			"fg_packed": flt(c.produced_qty),
			"rejection": flt(c.rejection_qty),
			"rejection_reason": c.rejection_reason,
			"actual": actual,
			"balance": balance,
			"achievement_pct": _pct(c.produced_qty, c.target_qty),
			"status": _band(c.produced_qty, c.target_qty),
			"remarks": c.remarks,
		}
		data.append(vals)
		for f in _SUM_FIELDS:
			subtotal[f] += vals[f]
			grand[f] += vals[f]

	# final line subtotal + grand total
	flush_subtotal(cur_line)
	if any(grand[f] for f in _SUM_FIELDS):
		grow = {"line": "GRAND TOTAL", "is_subtotal": 1}
		grow.update({f: grand[f] for f in _SUM_FIELDS})
		grow["achievement_pct"] = _pct(grand["fg_packed"], grand["target"])
		grow["status"] = _band(grand["fg_packed"], grand["target"])
		data.append(grow)

	return _columns(), data


def _bin_qty(warehouse):
	return flt(
		frappe.db.sql("SELECT COALESCE(SUM(actual_qty), 0) FROM `tabBin` WHERE warehouse = %s", warehouse)[0][0]
	)


def _zero():
	return {f: 0.0 for f in _SUM_FIELDS}


def _pct(fg, target):
	return flt(flt(fg) / flt(target) * 100.0, 1) if flt(target) else 0.0


def _band(fg, target):
	if not flt(target):
		return ""
	pct = flt(fg) / flt(target) * 100.0
	if pct >= 95:
		return "On Target"
	if pct >= 80:
		return "Warning"
	return "Action"


def _columns():
	return [
		{"label": _("Line"), "fieldname": "line", "fieldtype": "Data", "width": 120},
		{"label": _("Supervisor"), "fieldname": "supervisor", "fieldtype": "Link", "options": "User", "width": 140},
		{"label": _("Operators"), "fieldname": "operators", "fieldtype": "Int", "width": 85},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 130},
		{"label": _("Product"), "fieldname": "product", "fieldtype": "Data", "width": 240},
		{"label": _("Date"), "fieldname": "production_date", "fieldtype": "Date", "width": 100},
		{"label": _("Carry Fwd"), "fieldname": "carry_fwd", "fieldtype": "Float", "width": 95},
		{"label": _("New RM Issued"), "fieldname": "new_rm", "fieldtype": "Float", "width": 110},
		{"label": _("Target (CF+RM)"), "fieldname": "target", "fieldtype": "Float", "width": 110},
		{"label": _("RM Stock at Line"), "fieldname": "rm_at_line", "fieldtype": "Float", "width": 120},
		{"label": _("Assembled on Line"), "fieldname": "on_line", "fieldtype": "Float", "width": 120},
		{"label": _("Assembled on Aging"), "fieldname": "on_aging", "fieldtype": "Float", "width": 125},
		{"label": _("Assembled at Packing"), "fieldname": "at_packing", "fieldtype": "Float", "width": 130},
		{"label": _("FG Packed"), "fieldname": "fg_packed", "fieldtype": "Float", "width": 95},
		{"label": _("Rejection"), "fieldname": "rejection", "fieldtype": "Float", "width": 90},
		{"label": _("Rejection Reason"), "fieldname": "rejection_reason", "fieldtype": "Link", "options": "Lumirise Defect Code", "width": 140},
		{"label": _("Actual (FG)"), "fieldname": "actual", "fieldtype": "Float", "width": 95},
		{"label": _("Balance to Produce"), "fieldname": "balance", "fieldtype": "Float", "width": 120},
		{"label": _("Achievement %"), "fieldname": "achievement_pct", "fieldtype": "Percent", "width": 115},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 180},
		{"label": _("Job Card"), "fieldname": "job_card", "fieldtype": "Link", "options": "Lumirise Job Card", "width": 150},
	]
