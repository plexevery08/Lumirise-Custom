"""Lumirise custom fields on the standard Purchase Invoice.

lr_grn_date — the date the goods were received (from the linked GRN / Purchase
Receipt), placed next to the Supplier Invoice Date. Auto-filled on validate by
lumirise_custom.accounts.set_grn_date (latest linked GRN posting_date), but left
editable so it can be entered manually on a PI not made from a GRN.

Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def create_purchase_invoice_fields():
	# Anchor after the Supplier Invoice Date if present, else after posting_date.
	meta = frappe.get_meta("Purchase Invoice")
	anchor = "bill_date" if meta.has_field("bill_date") else "posting_date"
	fields = {
		"Purchase Invoice": [
			dict(
				fieldname="lr_grn_date",
				label="GRN Date",
				fieldtype="Date",
				insert_after=anchor,
				description="Date the goods were received (from the linked GRN). "
				            "Auto-filled from the latest linked Purchase Receipt; editable.",
				module="Lumirise Custom",
			)
		]
	}
	create_custom_fields(fields, update=True)
