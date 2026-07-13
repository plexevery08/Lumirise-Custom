"""Customer-PO capture + PO-match annotation fields on the STANDARD Sales Order (WP-1.4).

- lr_customer_po: the CUSTOMER's purchase order number, a dedicated Lumirise field.
  We do NOT reuse the standard `po_no` — in ERPNext `po_no` is also driven by the
  internal-transfer / inter-company sales flow, so it isn't a reliable place for the
  customer's PO. The PO-match validator keys off this field.
- lr_po_match_status / lr_po_match_note: read-only outputs filled by
  lumirise_custom.sales_po_match.validate_po_match on validate — a status
  (Not Checked / Matched / Exception) and a human note (blank/duplicate customer PO,
  or a line whose qty/rate drifts from the source Quotation).

Custom Fields — the upgrade-safe way to extend a doctype we don't own.
Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

SO_FIELDS = [
	dict(
		fieldname="lr_customer_po",
		label="Customer Purchase Order",
		fieldtype="Data",
		insert_after="customer_name",
		in_standard_filter=1,
		module="Lumirise Custom",
		translatable=0,
		description="The customer's own PO number (not the internal-transfer po_no). Drives the PO-match check.",
	),
	dict(
		fieldname="lr_po_match_status",
		label="PO Match",
		fieldtype="Select",
		options="\nNot Checked\nMatched\nException",
		insert_after="po_date",
		read_only=1,
		allow_on_submit=1,
		in_standard_filter=1,
		no_copy=1,
		module="Lumirise Custom",
		translatable=0,
	),
	dict(
		fieldname="lr_po_match_note",
		label="PO Match Note",
		fieldtype="Small Text",
		insert_after="lr_po_match_status",
		read_only=1,
		allow_on_submit=1,
		no_copy=1,
		module="Lumirise Custom",
		translatable=0,
	),
]


def create_sales_po_fields():
	create_custom_fields({"Sales Order": SO_FIELDS}, update=True)
