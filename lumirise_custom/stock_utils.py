"""Shared stock totals that understand group warehouses and rack descendants."""

import frappe
from frappe.utils import flt

from lumirise_custom import defaults as config


def warehouse_stock_qty(item_code, warehouse):
	if not warehouse:
		return 0.0
	bounds = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return 0.0
	return flt(
		frappe.db.sql(
			"""SELECT COALESCE(SUM(b.actual_qty),0)
			FROM `tabBin` b JOIN `tabWarehouse` w ON w.name=b.warehouse
			WHERE b.item_code=%s AND w.lft >= %s AND w.rgt <= %s""",
			(item_code, bounds.lft, bounds.rgt),
		)[0][0]
	)


def rm_stock_qty(item_code):
	return warehouse_stock_qty(item_code, config.rm_warehouse())


def inbound_target_warehouse():
	"""PO/GRN target before rack put-away."""
	return config.receiving_warehouse() or config.rm_warehouse()
