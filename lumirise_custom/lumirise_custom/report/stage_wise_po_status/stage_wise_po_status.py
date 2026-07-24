# Stage-wise PO Status — one row per open (or all) Purchase Order showing how far
# its material has travelled through the Lumirise inbound chain:
#
#   Ordered -> Vendor PDI approved -> Dispatched / In Transit (Inbound Logistics)
#   -> IQC accepted -> Received (GRN / Purchase Receipt) -> Billed
#
# plus a derived "Current Stage" label = the furthest stage that has any activity,
# so Purchase can answer "where is my PO?" without opening five doctypes.
# An "Item Detail" view breaks the same numbers down per PO line item.
#
# Client ask: Phase-2 tracker point 29 ("Completed purchase Order to Finishing
# Stage — stage-wise status report").

import frappe
from frappe import _
from frappe.utils import flt

STAGES = ["Ordered", "Vendor PDI", "In Transit", "IQC", "Received", "Billed", "Completed"]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if (filters.get("view") or "PO Summary") == "Item Detail":
		return _item_detail(filters)
	return _po_summary(filters)


def _po_conditions(filters):
	cond, vals = ["po.docstatus = 1"], {}
	if filters.get("supplier"):
		cond.append("po.supplier = %(supplier)s")
		vals["supplier"] = filters.supplier
	if filters.get("from_date"):
		cond.append("po.transaction_date >= %(from_date)s")
		vals["from_date"] = filters.from_date
	if filters.get("to_date"):
		cond.append("po.transaction_date <= %(to_date)s")
		vals["to_date"] = filters.to_date
	if not filters.get("include_closed"):
		cond.append("po.status not in ('Closed', 'Completed')")
	return " and ".join(cond), vals


def _stage_maps(po_names):
	"""Per-PO aggregates from every chain doctype, in one query each."""
	if not po_names:
		return {}, {}, {}, {}, {}
	pdi = dict(frappe.db.sql(
		"""select p.purchase_order, sum(i.approved_qty)
		from `tabVendor PDI` p join `tabVendor PDI Item` i on i.parent = p.name
		where p.docstatus = 1 and p.purchase_order in %s group by p.purchase_order""",
		(po_names,)))
	transit = dict(frappe.db.sql(
		"""select l.purchase_order, sum(i.qty)
		from `tabInbound Logistics` l join `tabInbound Logistics Item` i on i.parent = l.name
		where l.docstatus = 1 and l.purchase_order in %s group by l.purchase_order""",
		(po_names,)))
	iqc = dict(frappe.db.sql(
		"""select q.purchase_order, sum(i.accepted_qty)
		from `tabIQC` q join `tabIQC Item` i on i.parent = q.name
		where q.docstatus = 1 and q.purchase_order in %s group by q.purchase_order""",
		(po_names,)))
	received = dict(frappe.db.sql(
		"""select i.purchase_order, sum(i.received_qty)
		from `tabPurchase Receipt Item` i join `tabPurchase Receipt` r on r.name = i.parent
		where r.docstatus = 1 and i.purchase_order in %s group by i.purchase_order""",
		(po_names,)))
	billed = dict(frappe.db.sql(
		"""select i.purchase_order, sum(i.qty)
		from `tabPurchase Invoice Item` i join `tabPurchase Invoice` b on b.name = i.parent
		where b.docstatus = 1 and i.purchase_order in %s group by i.purchase_order""",
		(po_names,)))
	return pdi, transit, iqc, received, billed


def _current_stage(row):
	if row.ordered_qty and flt(row.received_qty) >= flt(row.ordered_qty):
		return "Completed" if flt(row.billed_qty) >= flt(row.ordered_qty) else "Received"
	for stage, qty in (
		("Received", row.received_qty), ("IQC", row.iqc_qty),
		("In Transit", row.transit_qty), ("Vendor PDI", row.pdi_qty),
	):
		if flt(qty) > 0:
			return stage
	return "Ordered"


def _po_summary(filters):
	cond, vals = _po_conditions(filters)
	pos = frappe.db.sql(
		f"""select po.name, po.supplier, po.transaction_date, po.status,
			sum(poi.qty) as ordered_qty, po.grand_total, po.currency
		from `tabPurchase Order` po join `tabPurchase Order Item` poi on poi.parent = po.name
		where {cond} group by po.name order by po.transaction_date desc""",
		vals, as_dict=True)
	names = tuple(p.name for p in pos) or ("",)
	pdi, transit, iqc, received, billed = _stage_maps(names)
	rows = []
	for p in pos:
		p.pdi_qty = flt(pdi.get(p.name))
		p.transit_qty = flt(transit.get(p.name))
		p.iqc_qty = flt(iqc.get(p.name))
		p.received_qty = flt(received.get(p.name))
		p.billed_qty = flt(billed.get(p.name))
		p.pending_qty = max(flt(p.ordered_qty) - p.received_qty, 0)
		p.current_stage = _current_stage(p)
		if filters.get("stage") and p.current_stage != filters.stage:
			continue
		rows.append(p)
	columns = [
		{"label": _("Purchase Order"), "fieldname": "name", "fieldtype": "Link", "options": "Purchase Order", "width": 170},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 170},
		{"label": _("Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 95},
		{"label": _("Current Stage"), "fieldname": "current_stage", "fieldtype": "Data", "width": 110},
		{"label": _("Ordered Qty"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 100},
		{"label": _("PDI Approved"), "fieldname": "pdi_qty", "fieldtype": "Float", "width": 105},
		{"label": _("In Transit"), "fieldname": "transit_qty", "fieldtype": "Float", "width": 95},
		{"label": _("IQC Accepted"), "fieldname": "iqc_qty", "fieldtype": "Float", "width": 105},
		{"label": _("Received"), "fieldname": "received_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Billed"), "fieldname": "billed_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Pending"), "fieldname": "pending_qty", "fieldtype": "Float", "width": 90},
		{"label": _("PO Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
	]
	return columns, rows


def _item_detail(filters):
	cond, vals = _po_conditions(filters)
	rows = frappe.db.sql(
		f"""select po.name as purchase_order, po.supplier, poi.item_code, poi.item_name,
			poi.qty as ordered_qty, poi.received_qty, poi.qty - poi.received_qty as pending_qty
		from `tabPurchase Order` po join `tabPurchase Order Item` poi on poi.parent = po.name
		where {cond} order by po.transaction_date desc, poi.idx""",
		vals, as_dict=True)
	columns = [
		{"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link", "options": "Purchase Order", "width": 170},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 160},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 260},
		{"label": _("Ordered Qty"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Received"), "fieldname": "received_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Pending"), "fieldname": "pending_qty", "fieldtype": "Float", "width": 90},
	]
	return columns, rows
