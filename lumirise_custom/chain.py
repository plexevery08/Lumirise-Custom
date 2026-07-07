# "Create next" mappers that string the Focus 9 procurement/quality chain
# together for one-click data entry while filming:
#   Purchase Order -> Vendor PDI -> Inbound Logistics -> IQC -> GRN (Purchase Receipt)
#   Sales Order    -> Customer PDI
# Each is whitelisted for frappe.model.open_mapped_doc on the client.

import frappe
from frappe.utils import flt

STORES = "Stores - L"


@frappe.whitelist()
def make_vendor_pdi(source_name, target_doc=None):
	po = frappe.get_doc("Purchase Order", source_name)
	doc = frappe.new_doc("Vendor PDI")
	doc.purchase_order = po.name
	doc.mode = "Import" if "Import" in (po.supplier or "") else "Domestic"
	for it in po.items:
		doc.append("items", {"item_code": it.item_code, "item_name": it.item_name,
		                     "po_qty": it.qty, "approved_qty": it.qty})
	return doc


@frappe.whitelist()
def make_inbound_logistics(source_name, target_doc=None):
	vpdi = frappe.get_doc("Vendor PDI", source_name)
	doc = frappe.new_doc("Inbound Logistics")
	doc.vendor_pdi = vpdi.name
	doc.purchase_order = vpdi.purchase_order
	doc.mode = "Sea" if vpdi.mode == "Import" else "Road"
	doc.status = "Dispatched"
	# Only the qty accepted at Vendor PDI moves forward into transit.
	for it in vpdi.items:
		if flt(it.approved_qty) > 0:
			doc.append("items", {"item_code": it.item_code,
			                     "item_name": it.get("item_name") or frappe.db.get_value("Item", it.item_code, "item_name"),
			                     "qty": it.approved_qty})
	return doc


@frappe.whitelist()
def make_iqc(source_name, target_doc=None):
	log = frappe.get_doc("Inbound Logistics", source_name)
	doc = frappe.new_doc("IQC")
	doc.inbound_logistics = log.name
	doc.purchase_order = log.purchase_order
	doc.status = "IQC Received"
	for it in log.items:
		doc.append("items", {
			"item_code": it.item_code,
			"item_name": it.get("item_name") or frappe.db.get_value("Item", it.item_code, "item_name"),
			"received_qty": it.qty, "accepted_qty": it.qty, "rejected_qty": 0})
	return doc


@frappe.whitelist()
def make_grn(source_name, target_doc=None):
	"""GRN = standard Purchase Receipt against the IQC's PO.

	Ajay review 2026-06-14 (00:33:25-00:36:12): the GRN must reflect ACCEPTED stock
	only, with the rejected qty auto-fetched from the IQC into the rejected column
	and routed to the rejection warehouse -- so inventory is truthful and the
	rejection is visible downstream (it then drives the auto debit note).
	"""
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
	from lumirise_custom import defaults as config
	from frappe.utils import flt

	iqc = frappe.get_doc("IQC", source_name)
	pr = make_purchase_receipt(iqc.purchase_order)
	rej_wh = config.rejection_warehouse()

	# IQC rows grouped by item (lists -> consume per matching PR row).
	iqc_rows = {}
	for r in iqc.items:
		iqc_rows.setdefault(r.item_code, []).append(r)

	for it in pr.items:
		it.warehouse = STORES
		bucket = iqc_rows.get(it.item_code)
		if not bucket:
			continue
		r = bucket.pop(0)
		received = flt(r.received_qty) or flt(r.accepted_qty) + flt(r.rejected_qty)
		# ERPNext PR Item invariant: received_qty == qty(accepted) + rejected_qty.
		it.received_qty = received
		it.qty = flt(r.accepted_qty)
		it.rejected_qty = flt(r.rejected_qty)
		if flt(r.rejected_qty) > 0:
			it.rejected_warehouse = rej_wh
	return pr


# --- GRN -> IQC status sync (closes the inbound chain) -----------------------
# The GRN (Purchase Receipt) carries no link back to the IQC, but the IQC gate and
# make_grn both work PO-scoped, so we match the same way: on GRN submit, any passed
# IQC for the GRN's PO(s) is flipped to "Moved to RM". This is what removes its
# accepted qty from the "Pending IQC" bucket in Material Planning (the qty has now
# landed in the RM store as real Bin stock) — without it the qty would double-count.
# Assumption (v1, same as iqc_gate): one open passed IQC per PO per GRN.

def _grn_pos(doc):
	return {row.purchase_order for row in doc.items if getattr(row, "purchase_order", None)}


def mark_iqc_moved_to_rm(doc, method=None):
	"""On GRN submit: flip the passed IQC(s) for this PO to 'Moved to RM'."""
	if doc.get("is_subcontracted"):
		return  # subcontracting service PR — not an RM GRN, no IQC to close
	for po in _grn_pos(doc):
		for iqc in frappe.get_all(
			"IQC",
			filters={"purchase_order": po, "docstatus": 1, "status": "Passed"},
		):
			frappe.db.set_value("IQC", iqc.name, "status", "Moved to RM")


def revert_iqc_moved_to_rm(doc, method=None):
	"""On GRN cancel: re-open the IQC(s) so the qty returns to 'Pending IQC'."""
	if doc.get("is_subcontracted"):
		return
	for po in _grn_pos(doc):
		for iqc in frappe.get_all(
			"IQC",
			filters={"purchase_order": po, "docstatus": 1, "status": "Moved to RM"},
		):
			frappe.db.set_value("IQC", iqc.name, "status", "Passed")


@frappe.whitelist()
def make_customer_pdi(source_name, target_doc=None):
	"""Start a Customer PDI from a Sales Order — seed one inspection line per SO
	item. FG/Dispatch then sends these to the PDI store via store authorization."""
	so = frappe.get_doc("Sales Order", source_name)
	doc = frappe.new_doc("Customer PDI")
	doc.sales_order = so.name
	for it in so.items:
		doc.append("items", {"fg_item": it.item_code, "qty": it.qty})
	return doc


@frappe.whitelist()
def make_delivery_note(source_name, target_doc=None):
	"""Dispatch = standard Delivery Note against the Sales Order. Native mapping
	carries only the remaining (undelivered) qty, so partial / multi-batch dispatch
	off one SO is tracked automatically. FG is shipped from the Dispatch FG store.
	The Customer-PDI gate (events.py) blocks submission until a passed PDI exists."""
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note as _mdn
	from lumirise_custom import defaults as config

	dn = _mdn(source_name)
	dispatch_fg = config.dispatch_fg_warehouse()
	for it in dn.items:
		it.warehouse = dispatch_fg
	return dn


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None):
	"""Sales Invoice against a submitted Delivery Note (stock already moved by the
	DN; this is the billing document)."""
	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice as _msi

	return _msi(source_name)
