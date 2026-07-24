# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Batch Wise Rejection (Phase-2 point 30).
# Two rejection channels, one report:
#   1. Stock-level rejections -- every Stock Ledger Entry INTO a rejection
#      warehouse (name contains "Rejec"): GRN rejected-qty postings and
#      production line rejects. Batch comes from the SLE itself or, when the
#      movement used a Serial & Batch Bundle (v16), from the bundle's entries.
#   2. IQC rejections BEFORE GRN -- IQC Item.rejected_qty (no batch exists yet
#      at that point; the row says so explicitly instead of faking one).

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	data = _stock_rejections(filters) + _iqc_rejections(filters)
	data.sort(key=lambda d: str(d["posting_date"]), reverse=True)
	if filters.get("batch_no"):
		data = [d for d in data if d.get("batch_no") == filters["batch_no"]]
	return _columns(), data


def _columns():
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 95},
		{"fieldname": "source", "label": _("Source"), "fieldtype": "Data", "width": 110},
		{"fieldname": "voucher_type", "label": _("Voucher Type"), "fieldtype": "Data", "width": 120},
		{"fieldname": "voucher_no", "label": _("Voucher"), "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 160},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "batch_no", "label": _("Batch"), "fieldtype": "Link", "options": "Batch", "width": 140},
		{"fieldname": "rejected_qty", "label": _("Rejected Qty"), "fieldtype": "Float", "width": 105},
		{"fieldname": "warehouse", "label": _("Rejection Warehouse"), "fieldtype": "Link", "options": "Warehouse", "width": 160},
		{"fieldname": "remarks", "label": _("Detail"), "fieldtype": "Data", "width": 200},
	]


def _date_conditions(filters, field, values):
	out = []
	if filters.get("from_date"):
		out.append(f"{field} >= %(from_date)s")
		values["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		out.append(f"{field} <= %(to_date)s")
		values["to_date"] = filters["to_date"]
	return out


def _stock_rejections(filters):
	values = {}
	conditions = ["sle.is_cancelled = 0", "sle.actual_qty > 0", "w.name LIKE '%%Rejec%%'"]
	conditions += _date_conditions(filters, "sle.posting_date", values)
	if filters.get("item_code"):
		conditions.append("sle.item_code = %(item_code)s")
		values["item_code"] = filters["item_code"]

	rows = frappe.db.sql(
		f"""SELECT sle.posting_date, sle.voucher_type, sle.voucher_no,
		           sle.item_code, i.item_name, sle.batch_no, sle.actual_qty,
		           sle.warehouse, sle.serial_and_batch_bundle
		    FROM `tabStock Ledger Entry` sle
		    JOIN `tabWarehouse` w ON w.name = sle.warehouse
		    LEFT JOIN `tabItem` i ON i.name = sle.item_code
		    WHERE {' AND '.join(conditions)}
		    ORDER BY sle.posting_date DESC""",
		values, as_dict=True,
	)

	data = []
	for r in rows:
		batches = []
		if r.serial_and_batch_bundle:
			batches = frappe.db.sql(
				"""SELECT batch_no, SUM(qty) qty FROM `tabSerial and Batch Entry`
				   WHERE parent = %(b)s AND COALESCE(batch_no,'') != ''
				   GROUP BY batch_no""",
				{"b": r.serial_and_batch_bundle}, as_dict=True,
			)
		if batches:
			for b in batches:
				data.append(_stock_row(r, b.batch_no, abs(flt(b.qty))))
		else:
			data.append(_stock_row(r, r.batch_no, flt(r.actual_qty)))
	return data


def _stock_row(r, batch_no, qty):
	return {
		"posting_date": r.posting_date, "source": "Stock",
		"voucher_type": r.voucher_type, "voucher_no": r.voucher_no,
		"item_code": r.item_code, "item_name": r.item_name,
		"batch_no": batch_no, "rejected_qty": qty,
		"warehouse": r.warehouse,
		"remarks": "Moved into rejection warehouse",
	}


def _iqc_rejections(filters):
	values = {}
	conditions = ["q.docstatus < 2", "i.rejected_qty > 0"]
	conditions += _date_conditions(filters, "q.iqc_date", values)
	if filters.get("item_code"):
		conditions.append("i.item_code = %(item_code)s")
		values["item_code"] = filters["item_code"]

	rows = frappe.db.sql(
		f"""SELECT q.name, q.iqc_date, q.purchase_order, i.item_code, i.item_name,
		           i.rejected_qty, i.defect_code, i.reject_reason
		    FROM `tabIQC Item` i JOIN `tabIQC` q ON q.name = i.parent
		    WHERE {' AND '.join(conditions)}
		    ORDER BY q.iqc_date DESC""",
		values, as_dict=True,
	)
	return [{
		"posting_date": r.iqc_date, "source": "IQC (pre-GRN)",
		"voucher_type": "IQC", "voucher_no": r.name,
		"item_code": r.item_code, "item_name": r.item_name,
		"batch_no": None, "rejected_qty": flt(r.rejected_qty),
		"warehouse": None,
		"remarks": (f"PO {r.purchase_order} · " if r.purchase_order else "")
			+ (r.defect_code or r.reject_reason or "Rejected at incoming inspection"),
	} for r in rows]
