# "Create next" mappers that string the Focus 9 procurement/quality chain
# together for one-click data entry while filming:
#   Purchase Order -> Vendor PDI -> Inbound Logistics -> IQC -> GRN (Purchase Receipt)
#   Sales Order    -> Customer PDI
# Each is whitelisted for frappe.model.open_mapped_doc on the client.

import frappe

STORES = "Stores - L"


@frappe.whitelist()
def make_vendor_pdi(source_name, target_doc=None):
	po = frappe.get_doc("Purchase Order", source_name)
	doc = frappe.new_doc("Vendor PDI")
	doc.purchase_order = po.name
	doc.mode = "Import" if "Import" in (po.supplier or "") else "Domestic"
	for it in po.items:
		doc.append("items", {"item_code": it.item_code, "po_qty": it.qty, "approved_qty": it.qty})
	return doc


@frappe.whitelist()
def make_inbound_logistics(source_name, target_doc=None):
	vpdi = frappe.get_doc("Vendor PDI", source_name)
	doc = frappe.new_doc("Inbound Logistics")
	doc.vendor_pdi = vpdi.name
	doc.purchase_order = vpdi.purchase_order
	doc.mode = "Sea" if vpdi.mode == "Import" else "Road"
	for it in vpdi.items:
		doc.append("items", {"item_code": it.item_code, "qty": it.approved_qty})
	return doc


@frappe.whitelist()
def make_iqc(source_name, target_doc=None):
	log = frappe.get_doc("Inbound Logistics", source_name)
	doc = frappe.new_doc("IQC")
	doc.inbound_logistics = log.name
	doc.purchase_order = log.purchase_order
	for it in log.items:
		doc.append("items", {
			"item_code": it.item_code, "received_qty": it.qty,
			"accepted_qty": it.qty, "rejected_qty": 0})
	return doc


@frappe.whitelist()
def make_grn(source_name, target_doc=None):
	"""GRN = standard Purchase Receipt against the IQC's PO."""
	iqc = frappe.get_doc("IQC", source_name)
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
	pr = make_purchase_receipt(iqc.purchase_order)
	for it in pr.items:
		it.warehouse = STORES
	return pr


@frappe.whitelist()
def make_customer_pdi(source_name, target_doc=None):
	so = frappe.get_doc("Sales Order", source_name)
	doc = frappe.new_doc("Customer PDI")
	doc.sales_order = so.name
	doc.fg_item = so.items[0].item_code if so.items else None
	doc.sampled_qty = 20
	return doc
