# Custom fields that link the standard ERPNext documents into the Focus 9 flow.
# Owned by the "Lumirise Custom" module so they export as fixtures.
#
# Run:  bench --site site.com execute lumirise_custom.demo.build_customfields.execute

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Lumirise Custom"


def execute():
	create_custom_fields({
		"Sales Order": [
			dict(fieldname="lr_consignee", label="Consignee", fieldtype="Data",
				 insert_after="customer_name", module=MODULE),
			dict(fieldname="lr_status_sb", label="Lumirise Status", fieldtype="Section Break",
				 insert_after="delivery_date", module=MODULE, collapsible=1),
			dict(fieldname="lr_planning_status", label="Planning Status", fieldtype="Select",
				 options="\nPending\nPlanned", default="Pending", insert_after="lr_status_sb", module=MODULE),
			dict(fieldname="lr_purchase_status", label="Purchase Status", fieldtype="Select",
				 options="\nPending\nIndented\nOrdered\nReceived", default="Pending",
				 insert_after="lr_planning_status", module=MODULE),
			dict(fieldname="lr_production_status", label="Production Status", fieldtype="Select",
				 options="\nPending\nIn Production\nCompleted", default="Pending",
				 insert_after="lr_purchase_status", module=MODULE),
		],
		"Purchase Order": [
			dict(fieldname="lr_indent_refs", label="Indent References", fieldtype="Small Text",
				 insert_after="supplier", module=MODULE, read_only=1),
		],
		"Delivery Note": [
			dict(fieldname="lr_freight_terms", label="Freight Terms", fieldtype="Select",
				 options="\nTO PAY\nPAID", insert_after="customer_name", module=MODULE),
			dict(fieldname="lr_pod_attachment", label="POD", fieldtype="Attach",
				 insert_after="lr_freight_terms", module=MODULE),
		],
		"Work Order": [
			dict(fieldname="lr_source_planning", label="Source Planning", fieldtype="Link",
				 options="Material Planning", insert_after="sales_order", module=MODULE, read_only=1),
		],
	}, update=True)
	frappe.db.commit()
	print("Custom fields created.")
