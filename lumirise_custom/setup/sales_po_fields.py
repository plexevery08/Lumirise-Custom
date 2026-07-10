"""PO-match annotation fields on the STANDARD Sales Order (WP-1.4).

Two read-only fields filled by lumirise_custom.sales_po_match.validate_po_match on
validate: a status (Not Checked / Matched / Exception) and a human note listing what
didn't line up (blank/duplicate customer PO, or a line whose qty/rate drifts from the
source Quotation). Custom Fields — the upgrade-safe way to extend a doctype we don't own.

Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

SO_FIELDS = [
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
