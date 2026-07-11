"""Lumirise MD Production Dashboard (WP-P.5).

Replicates the client's weekly workbook MD Dashboard + Weekly Summary sheets in ERP:
a single-page view for the MD's Saturday review. KPI cards (week-to-date Plan /
Target / FG Packed / Rejection / Balance + the TWO ratios the client keeps distinct —
Plan-vs-Actual and Target-Achievement) over a day-wise table with their 95/80
achievement bands, driven entirely off Lumirise Job Cards.

Two ratios (their sheet, deliberately separate):
  - Plan vs Actual %   = FG packed / scheduled plan_qty   (how the plan is tracking)
  - Target Achievement % = FG packed / material target     (how the line did on what it got)
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, add_days, nowdate, formatdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.from_date or add_days(nowdate(), -6))
	to_date = getdate(filters.to_date or nowdate())
	if to_date < from_date:
		frappe.throw(_("To Date must be on or after From Date."))

	cards = frappe.get_all(
		"Lumirise Job Card",
		filters={"production_date": ["between", [from_date, to_date]], "docstatus": ["<", 2]},
		fields=["production_date", "plan_qty", "target_qty", "produced_qty", "rejection_qty"],
		limit_page_length=0,
	)

	# aggregate per day
	days = {}
	for c in cards:
		d = getdate(c.production_date)
		agg = days.setdefault(d, {"plan": 0.0, "target": 0.0, "fg": 0.0, "rej": 0.0})
		agg["plan"] += flt(c.plan_qty)
		agg["target"] += flt(c.target_qty)
		agg["fg"] += flt(c.produced_qty)
		agg["rej"] += flt(c.rejection_qty)

	data = []
	tot = {"plan": 0.0, "target": 0.0, "fg": 0.0, "rej": 0.0}
	day = from_date
	while day <= to_date:
		a = days.get(day, {"plan": 0.0, "target": 0.0, "fg": 0.0, "rej": 0.0})
		balance = max(0.0, a["target"] - a["fg"])
		ach = (a["fg"] / a["target"] * 100.0) if a["target"] else 0.0
		pva = (a["fg"] / a["plan"] * 100.0) if a["plan"] else 0.0
		data.append({
			"day": day,
			"plan_qty": a["plan"],
			"target_qty": a["target"],
			"fg_packed": a["fg"],
			"rejection": a["rej"],
			"balance": balance,
			"achievement_pct": ach,
			"plan_vs_actual_pct": pva,
			"status": _band(ach, a["target"], a["fg"]),
		})
		for k in tot:
			tot[k] += a[k]
		day = add_days(day, 1)

	tot_ach = (tot["fg"] / tot["target"] * 100.0) if tot["target"] else 0.0
	tot_pva = (tot["fg"] / tot["plan"] * 100.0) if tot["plan"] else 0.0
	tot_balance = max(0.0, tot["target"] - tot["fg"])

	report_summary = [
		{"label": _("Plan Qty"), "value": tot["plan"], "datatype": "Float", "indicator": "Blue"},
		{"label": _("Target Qty (issued)"), "value": tot["target"], "datatype": "Float", "indicator": "Blue"},
		{"label": _("FG Packed"), "value": tot["fg"], "datatype": "Float", "indicator": "Green"},
		{"label": _("Rejection"), "value": tot["rej"], "datatype": "Float", "indicator": "Red"},
		{"label": _("Balance to Produce"), "value": tot_balance, "datatype": "Float", "indicator": "Orange"},
		{"label": _("Plan vs Actual %"), "value": tot_pva, "datatype": "Percent",
		 "indicator": _pct_indicator(tot_pva)},
		{"label": _("Target Achievement %"), "value": tot_ach, "datatype": "Percent",
		 "indicator": _pct_indicator(tot_ach)},
	]

	chart = {
		"data": {
			"labels": [formatdate(r["day"], "dd-MM") for r in data],
			"datasets": [
				{"name": _("Plan"), "values": [r["plan_qty"] for r in data]},
				{"name": _("FG Packed"), "values": [r["fg_packed"] for r in data]},
			],
		},
		"type": "bar",
		"colors": ["#7cd6fd", "#28a745"],
	}

	return _columns(), data, None, chart, report_summary


def _band(ach, target, fg):
	if not target or not fg:
		return "No Data"
	if ach >= 95:
		return "On Target"
	if ach >= 80:
		return "Warning"
	return "Action"


def _pct_indicator(pct):
	if pct >= 95:
		return "Green"
	if pct >= 80:
		return "Orange"
	return "Red"


def _columns():
	return [
		{"label": _("Date"), "fieldname": "day", "fieldtype": "Date", "width": 110},
		{"label": _("Plan Qty"), "fieldname": "plan_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Target Qty"), "fieldname": "target_qty", "fieldtype": "Float", "width": 100},
		{"label": _("FG Packed"), "fieldname": "fg_packed", "fieldtype": "Float", "width": 100},
		{"label": _("Rejection"), "fieldname": "rejection", "fieldtype": "Float", "width": 90},
		{"label": _("Balance"), "fieldname": "balance", "fieldtype": "Float", "width": 100},
		{"label": _("Achievement %"), "fieldname": "achievement_pct", "fieldtype": "Percent", "width": 120},
		{"label": _("Plan vs Actual %"), "fieldname": "plan_vs_actual_pct", "fieldtype": "Percent", "width": 130},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
	]
