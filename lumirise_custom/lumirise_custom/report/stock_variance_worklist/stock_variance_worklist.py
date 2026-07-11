"""Stock Variance Worklist (WP-2.5).

There is no physical-count capture in the system yet, so this uses native **Stock
Reconciliation** rows as the count vehicle and diffs the counted qty against current
system stock (Bin.actual_qty). It is most useful BEFORE the Stock Reconciliation is
submitted — it shows the adjustment the SR will post; once submitted, system == counted
and the variance is 0 (the SR itself posted the correction).

This is a point-in-time diff, NOT a cycle-count programme (no schedules, count sheets,
bin freezes, or approval chain — that is a separate scope).
"""

import frappe
from frappe import _
from frappe.utils import flt

from lumirise_custom.lumirise_custom.report.rm_stock_and_reservation_tracker.rm_stock_and_reservation_tracker import (
	_warehouse_list,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	wh_list = _warehouse_list(filters)

	conds = "sr.docstatus < 2"
	params = {}
	if wh_list is not None:
		conds += " AND sri.warehouse IN %(whs)s"
		params["whs"] = tuple(wh_list) or ("",)
	if filters.get("item_group"):
		conds += " AND it.item_group = %(ig)s"
		params["ig"] = filters.item_group

	rows = frappe.db.sql(
		f"""SELECT sri.item_code, sri.warehouse, sri.qty AS counted,
			   sr.name AS sr, sr.posting_date, sr.docstatus
			FROM `tabStock Reconciliation Item` sri
			JOIN `tabStock Reconciliation` sr ON sr.name = sri.parent
			JOIN `tabItem` it ON it.name = sri.item_code
			WHERE {conds}
			ORDER BY sr.posting_date DESC, sr.creation DESC""",
		params,
		as_dict=True,
	)

	# latest count row per (item, warehouse)
	latest = {}
	for r in rows:
		latest.setdefault((r.item_code, r.warehouse), r)

	only_var = int(filters.get("only_variance") or 0)
	data = []
	for (item, wh), r in latest.items():
		system = flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "actual_qty"))
		counted = flt(r.counted)
		var = system - counted
		if only_var and abs(var) < 0.001:
			continue
		data.append({
			"item_code": item,
			"item_name": frappe.db.get_value("Item", item, "item_name"),
			"warehouse": wh,
			"system_qty": system,
			"counted_qty": counted,
			"variance": flt(var, 3),
			"variance_pct": flt(var / system * 100, 2) if system else 0.0,
			"count_date": r.posting_date,
			"count_doc": r.sr,
			"count_status": "Draft (will adjust)" if r.docstatus == 0 else "Adjusted",
			"status": "Match" if abs(var) < 0.001 else ("Short" if var > 0 else "Excess"),
		})

	if int(filters.get("include_never_counted") or 0):
		bin_conds = "b.actual_qty > 0"
		bp = {}
		if wh_list is not None:
			bin_conds += " AND b.warehouse IN %(whs)s"
			bp["whs"] = tuple(wh_list) or ("",)
		if filters.get("item_group"):
			bin_conds += " AND it.item_group = %(ig)s"
			bp["ig"] = filters.item_group
		for b in frappe.db.sql(
			f"""SELECT b.item_code, b.warehouse, b.actual_qty
				FROM `tabBin` b JOIN `tabItem` it ON it.name = b.item_code
				WHERE {bin_conds}""",
			bp,
			as_dict=True,
		):
			if (b.item_code, b.warehouse) in latest:
				continue
			data.append({
				"item_code": b.item_code,
				"item_name": frappe.db.get_value("Item", b.item_code, "item_name"),
				"warehouse": b.warehouse,
				"system_qty": flt(b.actual_qty),
				"counted_qty": None,
				"variance": None,
				"variance_pct": None,
				"count_date": None,
				"count_doc": None,
				"count_status": "",
				"status": "Never Counted",
			})

	data.sort(key=lambda d: abs(flt(d["variance"])), reverse=True)
	return _columns(), data


def _columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 170},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 180},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 150},
		{"label": _("System Qty"), "fieldname": "system_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Counted Qty"), "fieldname": "counted_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Variance"), "fieldname": "variance", "fieldtype": "Float", "width": 100},
		{"label": _("Variance %"), "fieldname": "variance_pct", "fieldtype": "Percent", "width": 100},
		{"label": _("Last Count"), "fieldname": "count_date", "fieldtype": "Date", "width": 100},
		{"label": _("Count Doc"), "fieldname": "count_doc", "fieldtype": "Link", "options": "Stock Reconciliation", "width": 150},
		{"label": _("Count Status"), "fieldname": "count_status", "fieldtype": "Data", "width": 120},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
	]
