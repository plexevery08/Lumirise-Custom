# Item-wise RM Summary — the client's "how much RM is in the RM store and how much
# is on each line" screen (Phase-2 tracker point 50). One row per raw-material item:
#
#   RM Store | On Lines (sum over line warehouses) | IQC Lab | Rejection | Other
#   | Total On Hand | Committed to open WOs | Free (Total - Committed)
#
# A "Line Detail" view gives one row per (item x line warehouse) so a supervisor can
# see exactly which line is holding stock. Warehouse classification comes from
# Lumirise Operations Settings via defaults.py, so this report follows any future
# warehouse re-mapping automatically.

import frappe
from frappe import _
from frappe.utils import flt

from lumirise_custom import defaults

RM_ITEM_GROUPS = ("Raw Material", "LED Raw Material")


def _bins(item_groups):
	return frappe.db.sql(
		"""select b.item_code, i.item_name, i.item_group, b.warehouse, b.actual_qty, b.reserved_qty
		from `tabBin` b
		join `tabItem` i on i.name = b.item_code
		where i.item_group in %s and i.disabled = 0 and b.actual_qty != 0""",
		(tuple(item_groups),), as_dict=True)


def _classify(warehouse, rm_wh, line_whs, iqc_wh, rej_wh):
	if warehouse == rm_wh:
		return "rm_store"
	if warehouse in line_whs:
		return "on_lines"
	if iqc_wh and warehouse == iqc_wh:
		return "iqc_lab"
	if rej_wh and warehouse == rej_wh:
		return "rejection"
	return "other"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	groups = [filters.item_group] if filters.get("item_group") in RM_ITEM_GROUPS else list(RM_ITEM_GROUPS)
	rm_wh = defaults.rm_warehouse()
	line_whs = {l["line_warehouse"] for l in defaults.production_lines(active_only=False)}
	try:
		iqc_wh = defaults.iqc_lab_warehouse()
	except Exception:
		iqc_wh = None  # IQC lab warehouse not configured yet — bucket falls to Other
	rej_wh = defaults.rejection_warehouse(required=False)
	bins = _bins(groups)

	if (filters.get("view") or "Summary by Item") == "Line Detail":
		rows = [b for b in bins if b.warehouse in line_whs]
		if filters.get("item_code"):
			rows = [b for b in rows if b.item_code == filters.item_code]
		columns = [
			{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
			{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 280},
			{"label": _("Line Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 200},
			{"label": _("Qty on Line"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 110},
		]
		return columns, rows

	agg = {}
	for b in bins:
		if filters.get("item_code") and b.item_code != filters.item_code:
			continue
		row = agg.setdefault(b.item_code, frappe._dict(
			item_code=b.item_code, item_name=b.item_name, item_group=b.item_group,
			rm_store=0, on_lines=0, iqc_lab=0, rejection=0, other=0, total=0, reserved=0))
		bucket = _classify(b.warehouse, rm_wh, line_whs, iqc_wh, rej_wh)
		row[bucket] += flt(b.actual_qty)
		row.total += flt(b.actual_qty)
		row.reserved += flt(b.reserved_qty)
	rows = sorted(agg.values(), key=lambda r: r.item_code)
	for r in rows:
		r.free = r.total - r.reserved
	columns = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 280},
		{"label": _("Group"), "fieldname": "item_group", "fieldtype": "Data", "width": 120},
		{"label": _("RM Store"), "fieldname": "rm_store", "fieldtype": "Float", "width": 95},
		{"label": _("On Lines"), "fieldname": "on_lines", "fieldtype": "Float", "width": 95},
		{"label": _("IQC Lab"), "fieldname": "iqc_lab", "fieldtype": "Float", "width": 90},
		{"label": _("Rejection"), "fieldname": "rejection", "fieldtype": "Float", "width": 90},
		{"label": _("Other WH"), "fieldname": "other", "fieldtype": "Float", "width": 90},
		{"label": _("Total On Hand"), "fieldname": "total", "fieldtype": "Float", "width": 110},
		{"label": _("Reserved"), "fieldname": "reserved", "fieldtype": "Float", "width": 95},
		{"label": _("Free"), "fieldname": "free", "fieldtype": "Float", "width": 90},
	]
	return columns, rows
