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
	# Single source of truth shared with the daily hold-timer scheduler — hold_days
	# defaults from Lumirise Operations Settings when the filter is blank (WP-2.4).
	from lumirise_custom.stores import aged_rejection_rows

	return aged_rejection_rows(filters.get("warehouse"), filters.get("hold_days"))
