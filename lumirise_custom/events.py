# Cross-doctype gates that enforce the Focus 9 quality flow on STANDARD ERPNext
# documents (we own these via doc_events in hooks.py, not by editing ERPNext):
#   - Purchase Receipt (= GRN) cannot submit until a passed IQC exists for its PO.
#   - Delivery Note (= Dispatch) cannot submit until a passed Customer PDI exists
#     for its Sales Order.

import frappe


def iqc_gate(doc, method=None):
	"""Block GRN (Purchase Receipt) submission unless IQC passed for the PO."""
	pos = {row.purchase_order for row in doc.items if getattr(row, "purchase_order", None)}
	for po in pos:
		iqc = frappe.get_all(
			"IQC",
			filters={"purchase_order": po, "docstatus": 1, "result": ["!=", "Rejected"]},
			limit=1)
		if not iqc:
			frappe.throw(
				f"IQC not cleared for Purchase Order <b>{po}</b>. "
				f"Goods cannot enter stock until Incoming Quality Control passes "
				f"(Vendor PDI → Logistics → IQC → GRN).",
				title="IQC Gate")


def customer_pdi_gate(doc, method=None):
	"""Block Delivery Note (Dispatch) submission unless Customer PDI passed for the SO."""
	sos = {row.against_sales_order for row in doc.items if getattr(row, "against_sales_order", None)}
	for so in sos:
		passed = frappe.get_all(
			"Customer PDI",
			filters={"sales_order": so, "docstatus": 1, "customer_signoff": "Pass"},
			limit=1)
		if not passed:
			frappe.throw(
				f"Customer PDI not passed for Sales Order <b>{so}</b>. "
				f"The lot cannot be dispatched until pre-dispatch inspection is signed off.",
				title="Customer PDI Gate")
