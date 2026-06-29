# RM Rejection Ageing — the Stores "held ~1 month then scrap" rule made visible.
# Lists material currently sitting in the rejection warehouse with how long it has
# been held, and flags anything past the hold window as "Scrap due" so rejected
# stock stops sitting forever as an invisible note (the C-4 / Stores #10 fix).

import frappe
from frappe import _
from frappe.utils import flt, getdate, date_diff, nowdate


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def _default_rejection_warehouse():
	try:
		wh = frappe.db.get_single_value("Lumirise Operations Settings", "rejection_warehouse")
		if wh:
			return wh
	except Exception:
		pass
	return frappe.db.get_value("Warehouse", {"warehouse_name": "RM Rejection"}, "name")


def get_columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 180},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 150},
		{"label": _("Held Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 100},
		{"label": _("Oldest In"), "fieldname": "oldest_in", "fieldtype": "Date", "width": 100},
		{"label": _("Age (days)"), "fieldname": "age_days", "fieldtype": "Int", "width": 90},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
	]


def get_data(filters):
	warehouse = filters.get("warehouse") or _default_rejection_warehouse()
	if not warehouse:
		return []
	hold_days = int(filters.get("hold_days") or 30)

	bins = frappe.get_all(
		"Bin",
		filters={"warehouse": warehouse, "actual_qty": [">", 0]},
		fields=["item_code", "actual_qty"],
	)
	rows = []
	today = getdate(nowdate())
	for b in bins:
		oldest = frappe.db.sql(
			"""SELECT MIN(posting_date) FROM `tabStock Ledger Entry`
			   WHERE warehouse=%(wh)s AND item_code=%(it)s AND actual_qty > 0
			     AND is_cancelled = 0""",
			{"wh": warehouse, "it": b.item_code},
		)
		oldest_in = oldest[0][0] if oldest and oldest[0] else None
		age = date_diff(today, getdate(oldest_in)) if oldest_in else 0
		rows.append({
			"item_code": b.item_code,
			"item_name": frappe.db.get_value("Item", b.item_code, "item_name"),
			"warehouse": warehouse,
			"qty": flt(b.actual_qty),
			"oldest_in": oldest_in,
			"age_days": age,
			"status": "Scrap due" if age >= hold_days else "Holding",
		})
	rows.sort(key=lambda r: r["age_days"], reverse=True)
	return rows
