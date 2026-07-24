# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# PO Stage Status (Phase-2 point 29): every Purchase Order line tracked through
# its inbound journey -- Vendor -> Vendor PDI -> In Transit -> IQC/Reached -> GRN.
# Stage quantities come from material_planning.po_stage_map (the SAME stage
# definitions the planning cockpit uses -- one source of truth, no drift):
# a qty sits in exactly ONE stage (its furthest live document), so
#   Pending at Vendor + At PDI + In Transit + At IQC + Received == Ordered.

import frappe
from frappe import _
from frappe.utils import flt

from lumirise_custom.lumirise_custom.doctype.material_planning.material_planning import (
	po_stage_map,
)


def execute(filters=None):
	filters = filters or {}
	conditions = ["po.docstatus = 1"]
	values = {}
	if not filters.get("include_closed"):
		conditions.append("po.status NOT IN ('Closed', 'Completed')")
	if filters.get("supplier"):
		conditions.append("po.supplier = %(supplier)s")
		values["supplier"] = filters["supplier"]
	if filters.get("from_date"):
		conditions.append("po.transaction_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("po.transaction_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]
	if filters.get("purchase_order"):
		conditions.append("po.name = %(purchase_order)s")
		values["purchase_order"] = filters["purchase_order"]

	lines = frappe.db.sql(
		f"""SELECT po.name po, po.transaction_date, po.supplier, po.status,
		           poi.item_code, poi.item_name, poi.qty, poi.received_qty
		    FROM `tabPurchase Order Item` poi
		    JOIN `tabPurchase Order` po ON po.name = poi.parent
		    WHERE {' AND '.join(conditions)}
		    ORDER BY po.transaction_date DESC, po.name, poi.idx""",
		values, as_dict=True,
	)

	stage_cache = {}
	data = []
	for l in lines:
		if l.po not in stage_cache:
			stage_cache[l.po] = po_stage_map(l.po)
		st = stage_cache[l.po].get(l.item_code, {})
		at_pdi = flt(st.get("at_pdi"))
		in_transit = flt(st.get("in_transit"))
		at_iqc = flt(st.get("at_iqc"))
		received = flt(l.received_qty)
		pending_vendor = max(0, flt(l.qty) - received - at_pdi - in_transit - at_iqc)

		if received >= flt(l.qty) - 0.0001:
			stage = "Received"
		elif at_iqc:
			stage = "At IQC / Reached"
		elif in_transit:
			stage = "In Transit"
		elif at_pdi:
			stage = "At Vendor PDI"
		else:
			stage = "With Vendor"

		data.append({
			"purchase_order": l.po, "transaction_date": l.transaction_date,
			"supplier": l.supplier, "item_code": l.item_code, "item_name": l.item_name,
			"ordered_qty": flt(l.qty), "pending_vendor": pending_vendor,
			"at_pdi": at_pdi, "in_transit": in_transit, "at_iqc": at_iqc,
			"received_qty": received,
			"pct_received": (received / flt(l.qty) * 100) if flt(l.qty) else 0,
			"stage": stage,
		})
	return _columns(), data


def _columns():
	return [
		{"fieldname": "purchase_order", "label": _("Purchase Order"), "fieldtype": "Link", "options": "Purchase Order", "width": 160},
		{"fieldname": "transaction_date", "label": _("Date"), "fieldtype": "Date", "width": 95},
		{"fieldname": "supplier", "label": _("Supplier"), "fieldtype": "Link", "options": "Supplier", "width": 150},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "ordered_qty", "label": _("Ordered"), "fieldtype": "Float", "width": 90},
		{"fieldname": "pending_vendor", "label": _("With Vendor"), "fieldtype": "Float", "width": 100},
		{"fieldname": "at_pdi", "label": _("At Vendor PDI"), "fieldtype": "Float", "width": 105},
		{"fieldname": "in_transit", "label": _("In Transit"), "fieldtype": "Float", "width": 90},
		{"fieldname": "at_iqc", "label": _("At IQC / Reached"), "fieldtype": "Float", "width": 120},
		{"fieldname": "received_qty", "label": _("Received (GRN)"), "fieldtype": "Float", "width": 110},
		{"fieldname": "pct_received", "label": _("% Received"), "fieldtype": "Percent", "width": 95},
		{"fieldname": "stage", "label": _("Current Stage"), "fieldtype": "Data", "width": 130},
	]
