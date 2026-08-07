import frappe
from frappe import _
from frappe.utils import flt

from lumirise_custom import defaults as config


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{
			"label": _("Location"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 220,
		},
		{"label": _("Barcode"), "fieldname": "location_barcode", "fieldtype": "Data", "width": 150},
		{"label": _("Status"), "fieldname": "slot_status", "fieldtype": "Data", "width": 90},
		{"label": _("Capacity"), "fieldname": "capacity", "fieldtype": "Float", "width": 90},
		{"label": _("Occupied"), "fieldname": "occupied", "fieldtype": "Float", "width": 90},
		{"label": _("Available"), "fieldname": "available", "fieldtype": "Float", "width": 90},
		{"label": _("UOM"), "fieldname": "capacity_uom", "fieldtype": "Link", "options": "UOM", "width": 70},
		{"label": _("Packages"), "fieldname": "package_count", "fieldtype": "Int", "width": 80},
		{
			"label": _("Allowed Group"),
			"fieldname": "allowed_item_group",
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 130,
		},
	]

	root = config.rm_warehouse()
	lft, rgt = frappe.db.get_value("Warehouse", root, ["lft", "rgt"])
	conditions = ["w.lft > %(lft)s", "w.rgt < %(rgt)s", "w.is_group = 0", "w.disabled = 0"]
	params = {"lft": lft, "rgt": rgt}
	if filters.get("slot_status"):
		conditions.append("COALESCE(w.lr_slot_status, 'Available') = %(slot_status)s")
		params["slot_status"] = filters.slot_status
	rows = frappe.db.sql(
		f"""
		SELECT w.name AS warehouse, w.lr_location_barcode AS location_barcode,
			COALESCE(w.lr_slot_status, 'Available') AS slot_status,
			COALESCE(w.lr_slot_capacity, 0) AS capacity,
			w.lr_slot_capacity_uom AS capacity_uom,
			w.lr_allowed_item_group AS allowed_item_group,
			COALESCE(SUM(b.actual_qty), 0) AS occupied
		FROM `tabWarehouse` w
		LEFT JOIN `tabBin` b ON b.warehouse = w.name
		WHERE {" AND ".join(conditions)}
		GROUP BY w.name
		ORDER BY w.lft
		""",
		params,
		as_dict=True,
	)
	counts = {
		r.current_warehouse: r.count
		for r in frappe.db.sql(
			"""SELECT current_warehouse, COUNT(*) AS count FROM `tabRM Receiving Package`
		WHERE remaining_qty>0 AND COALESCE(current_warehouse, '')!='' GROUP BY current_warehouse""",
			as_dict=True,
		)
	}
	for row in rows:
		row.package_count = counts.get(row.warehouse, 0)
		row.available = max(0, flt(row.capacity) - flt(row.occupied)) if flt(row.capacity) else None
	return columns, rows
