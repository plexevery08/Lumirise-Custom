"""Line Status (WP-3.1) — the live per-line production board.

One row per active production line: open Work Orders feeding it, current on-line
stock, today's Job Card target vs actual (with the 95/80 achievement band), and the
last Line Daily Closing variance/balance. Reads the Operations Settings production_lines
child rows (canonical for warehouse metrics) and joins Job Card / Line Daily Closing by
the child-row name (how they store production_line — see lumirise-production-planning-module).
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	settings = frappe.get_cached_doc("Lumirise Operations Settings")
	today = getdate(nowdate())
	data = []

	for r in settings.production_lines:
		if not r.is_active:
			continue
		line_wh = r.line_warehouse

		# open Work Orders that have had material transferred to this line
		open_wos = 0
		for w in frappe.db.sql(
			"""SELECT DISTINCT work_order FROM `tabStock Entry`
			   WHERE stock_entry_type = 'Internal Stock Transfer to Line'
				 AND docstatus = 1 AND to_warehouse = %s AND work_order IS NOT NULL""",
			line_wh,
			as_dict=True,
		):
			q, p, st = frappe.db.get_value("Work Order", w.work_order, ["qty", "produced_qty", "status"]) or (0, 0, None)
			if st not in ("Completed", "Stopped", "Closed") and flt(q) > flt(p):
				open_wos += 1

		on_line = flt(
			frappe.db.sql("SELECT COALESCE(SUM(actual_qty), 0) FROM `tabBin` WHERE warehouse = %s", line_wh)[0][0]
		)

		jc = frappe.db.sql(
			"""SELECT COALESCE(SUM(target_qty), 0), COALESCE(SUM(produced_qty), 0)
			   FROM `tabLumirise Job Card`
			   WHERE production_line = %s AND production_date = %s AND docstatus < 2""",
			(line_wh, today),
		)[0]
		t_target, t_prod = flt(jc[0]), flt(jc[1])
		ach = (t_prod / t_target * 100.0) if t_target else 0.0

		lc = frappe.db.sql(
			"""SELECT closing_date, variance, is_balanced FROM `tabLine Daily Closing`
			   WHERE production_line = %s AND docstatus = 1
			   ORDER BY closing_date DESC, creation DESC LIMIT 1""",
			line_wh,
			as_dict=True,
		)
		lc = lc[0] if lc else None

		data.append({
			"line": r.line_name,
			"warehouse": line_wh,
			"supervisor": r.supervisor_user,
			"open_wos": open_wos,
			"on_line_qty": on_line,
			"today_target": t_target,
			"today_produced": t_prod,
			"today_variance": flt(t_prod - t_target, 2),
			"achievement_pct": flt(ach, 1),
			"status": _band(ach, t_target, t_prod),
			"last_closing": lc.closing_date if lc else None,
			"last_closing_variance": flt(lc.variance) if lc else None,
			"balanced": lc.is_balanced if lc else None,
		})

	return _columns(), data


def _band(ach, target, produced):
	if not target or not produced:
		return "No Data"
	if ach >= 95:
		return "On Target"
	if ach >= 80:
		return "Warning"
	return "Action"


def _columns():
	return [
		{"label": _("Line"), "fieldname": "line", "fieldtype": "Data", "width": 90},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 140},
		{"label": _("Supervisor"), "fieldname": "supervisor", "fieldtype": "Link", "options": "User", "width": 150},
		{"label": _("Open WOs"), "fieldname": "open_wos", "fieldtype": "Int", "width": 90},
		{"label": _("On-Line Stock"), "fieldname": "on_line_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Today Target"), "fieldname": "today_target", "fieldtype": "Float", "width": 100},
		{"label": _("Today Produced"), "fieldname": "today_produced", "fieldtype": "Float", "width": 110},
		{"label": _("Today Var"), "fieldname": "today_variance", "fieldtype": "Float", "width": 90},
		{"label": _("Achievement %"), "fieldname": "achievement_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Last Closing"), "fieldname": "last_closing", "fieldtype": "Date", "width": 100},
		{"label": _("Last Var"), "fieldname": "last_closing_variance", "fieldtype": "Float", "width": 90},
		{"label": _("Balanced"), "fieldname": "balanced", "fieldtype": "Check", "width": 80},
	]
