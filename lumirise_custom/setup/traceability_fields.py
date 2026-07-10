"""Lumirise Traceability panel on the STANDARD doctypes in the SO -> SI chain.

Adds a collapsible "Lumirise Traceability" section holding four read-only Small Text
fields — Sales Order / Indent / Work Order / Purchase Order references — filled by
lumirise_custom.traceability.stamp on validate. Small Text (comma-string), not Link,
because the netting procurement leg is many-to-many (see traceability.py header).

Standard doctypes only (Property Setters / Custom Fields are the upgrade-safe way to
touch doctypes we don't own). The custom doctypes in the chain (Vendor PDI, Inbound
Logistics, IQC, Customer PDI, Indent, Material Receipt) carry these fields directly in
their JSON per the owned-doctype rule.

Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Standard doctypes that get the panel, each with the field its section sits after.
# (insert_after just anchors the section break near the end of the main body.)
TARGETS = {
	"Sales Order": "items",
	"Work Order": "items",
	"Purchase Order": "items",
	"Purchase Receipt": "items",
	"Purchase Invoice": "items",
	"Delivery Note": "items",
	"Sales Invoice": "items",
	"Stock Entry": "items",
}

_REF_FIELDS = [
	("lr_source_so", "Sales Order Ref"),
	("lr_source_indent", "Indent Ref"),
	("lr_source_wo", "Work Order Ref"),
	("lr_source_po", "Purchase Order Ref"),
]


def _panel_for(anchor):
	"""The section-break + four read-only Small Text fields for one doctype."""
	fields = [
		dict(
			fieldname="lr_traceability_sec",
			label="Lumirise Traceability",
			fieldtype="Section Break",
			insert_after=anchor,
			collapsible=1,
			module="Lumirise Custom",
		)
	]
	prev = "lr_traceability_sec"
	for fieldname, label in _REF_FIELDS:
		fields.append(
			dict(
				fieldname=fieldname,
				label=label,
				fieldtype="Small Text",
				insert_after=prev,
				read_only=1,
				no_copy=1,
				allow_on_submit=1,   # restamp() writes these after submit
				module="Lumirise Custom",
			)
		)
		prev = fieldname
	return fields


def create_traceability_fields():
	custom_fields = {dt: _panel_for(anchor) for dt, anchor in TARGETS.items()}
	create_custom_fields(custom_fields, update=True)
	frappe.clear_cache()
