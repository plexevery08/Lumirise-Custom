"""Operational custom fields for the production-to-dispatch flow.

Currently: a free-text Narration on Stock Entry so the operator can record why a
movement was made (which is distinct from the system Remarks). Tagged to the
Lumirise Custom module so it ships in the app's Custom Field fixtures.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

STOCK_ENTRY_FIELDS = [
	dict(
		fieldname="custom_narration",
		label="Narration",
		fieldtype="Small Text",
		insert_after="remarks",
		module="Lumirise Custom",
		translatable=0,
		description="Free-text note on why this stock movement was made.",
	),
]


def create_flow_fields():
	create_custom_fields({"Stock Entry": STOCK_ENTRY_FIELDS}, update=True)
