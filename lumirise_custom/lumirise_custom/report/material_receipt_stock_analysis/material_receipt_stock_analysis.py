# Material Receipt Stock Analysis — the stock view that opens off a submitted
# Material Receipt. One row per receipt line: what the RM store issued, what the
# factory actually accepted, and what's missing (shortfall), with the live stock
# on hand at the receiving warehouse plus links back to the Work Order and the
# source issue Stock Entry. This is the "where did the stock go / what's short"
# picture Ajay asked for at the RM hand-off (review 2026-06-14).

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	report_summary = get_summary(data)
	chart = get_chart(data)
	return columns, data, None, chart, report_summary


def get_columns():
	return [
		{"label": _("Material Receipt"), "fieldname": "material_receipt", "fieldtype": "Link", "options": "Material Receipt", "width": 150},
		{"label": _("Receipt Date"), "fieldname": "receipt_date", "fieldtype": "Date", "width": 100},
		{"label": _("Ack."), "fieldname": "acknowledged", "fieldtype": "Check", "width": 50},
		{"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 140},
		{"label": _("Source Issue (Stock Entry)"), "fieldname": "source_stock_entry", "fieldtype": "Link", "options": "Stock Entry", "width": 160},
		{"label": _("Received At"), "fieldname": "warehouse", "fieldtype": "Data", "width": 150},
		{"label": _("Received By"), "fieldname": "received_by", "fieldtype": "Link", "options": "User", "width": 140},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 180},
		{"label": _("Issued Qty"), "fieldname": "issued_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Accepted Qty"), "fieldname": "received_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Missing (Shortfall)"), "fieldname": "shortfall_qty", "fieldtype": "Float", "width": 130},
		{"label": _("Shortfall %"), "fieldname": "shortfall_pct", "fieldtype": "Percent", "width": 100},
		{"label": _("Stock on Hand"), "fieldname": "stock_on_hand", "fieldtype": "Float", "width": 110},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Link", "options": "UOM", "width": 70},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 180},
	]


def get_data(filters):
	conditions = ["mr.docstatus < 2"]
	params = {}
	if not filters.get("include_draft"):
		conditions = ["mr.docstatus = 1"]
	if filters.get("material_receipt"):
		conditions.append("mr.name = %(material_receipt)s")
		params["material_receipt"] = filters["material_receipt"]
	if filters.get("work_order"):
		conditions.append("mr.work_order = %(work_order)s")
		params["work_order"] = filters["work_order"]
	if filters.get("source_stock_entry"):
		conditions.append("mr.source_stock_entry = %(source_stock_entry)s")
		params["source_stock_entry"] = filters["source_stock_entry"]
	if filters.get("item_code"):
		conditions.append("mri.item_code = %(item_code)s")
		params["item_code"] = filters["item_code"]
	if filters.get("from_date"):
		conditions.append("mr.receipt_date >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("mr.receipt_date <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("only_shortfalls"):
		conditions.append("mri.shortfall_qty > 0")

	where = " AND ".join(conditions)
	rows = frappe.db.sql(
		f"""
		SELECT
			mr.name           AS material_receipt,
			mr.receipt_date   AS receipt_date,
			mr.acknowledged   AS acknowledged,
			mr.work_order     AS work_order,
			mr.source_stock_entry AS source_stock_entry,
			mr.from_warehouse AS warehouse,
			mr.received_by    AS received_by,
			mri.item_code     AS item_code,
			mri.item_name     AS item_name,
			mri.issued_qty    AS issued_qty,
			mri.received_qty  AS received_qty,
			mri.shortfall_qty AS shortfall_qty,
			mri.uom           AS uom,
			mri.remarks       AS remarks
		FROM `tabMaterial Receipt` mr
		INNER JOIN `tabMaterial Receipt Item` mri ON mri.parent = mr.name
		WHERE {where}
		ORDER BY mr.receipt_date DESC, mr.name DESC, mri.idx ASC
		""",
		params,
		as_dict=True,
	)

	for r in rows:
		issued = flt(r.issued_qty)
		r.shortfall_pct = (flt(r.shortfall_qty) / issued * 100.0) if issued else 0.0
		r.stock_on_hand = _stock_on_hand(r.item_code, r.warehouse)
	return rows


def _stock_on_hand(item_code, warehouse):
	"""Live actual_qty for the item at the receiving warehouse. from_warehouse is a
	plain Data field holding the warehouse name; if it isn't a real warehouse (e.g. a
	free-text quarantine label) there's simply no Bin and we show 0."""
	if not item_code or not warehouse:
		return 0.0
	qty = frappe.db.get_value(
		"Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
	)
	return flt(qty)


def get_summary(data):
	total_issued = sum(flt(r.get("issued_qty")) for r in data)
	total_accepted = sum(flt(r.get("received_qty")) for r in data)
	total_short = sum(flt(r.get("shortfall_qty")) for r in data)
	short_lines = sum(1 for r in data if flt(r.get("shortfall_qty")) > 0)
	return [
		{"label": _("Total Issued"), "value": total_issued, "datatype": "Float", "indicator": "Blue"},
		{"label": _("Total Accepted"), "value": total_accepted, "datatype": "Float", "indicator": "Green"},
		{"label": _("Total Missing"), "value": total_short, "datatype": "Float",
		 "indicator": "Red" if total_short else "Green"},
		{"label": _("Lines with Shortfall"), "value": short_lines, "datatype": "Int",
		 "indicator": "Red" if short_lines else "Green"},
	]


def get_chart(data):
	if not data:
		return None
	# Per-item Issued vs Accepted, capped to the 15 biggest lines so the chart stays readable.
	by_item = {}
	for r in data:
		k = r.get("item_code") or "—"
		agg = by_item.setdefault(k, {"issued": 0.0, "accepted": 0.0})
		agg["issued"] += flt(r.get("issued_qty"))
		agg["accepted"] += flt(r.get("received_qty"))
	items = sorted(by_item.items(), key=lambda kv: kv[1]["issued"], reverse=True)[:15]
	return {
		"data": {
			"labels": [k for k, _v in items],
			"datasets": [
				{"name": _("Issued"), "values": [v["issued"] for _k, v in items]},
				{"name": _("Accepted"), "values": [v["accepted"] for _k, v in items]},
			],
		},
		"type": "bar",
		"colors": ["#5e64ff", "#28a745"],
	}
