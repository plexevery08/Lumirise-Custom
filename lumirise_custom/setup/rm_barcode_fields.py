"""Upgrade-safe fields on ERPNext doctypes used by the RM barcode flow."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def create_rm_barcode_fields():
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": "lr_rm_barcode_tracking",
					"label": "Track RM Packages",
					"fieldtype": "Check",
					"insert_after": "has_batch_no",
					"description": "Require Lumirise package/LPN scans for this raw material.",
					"module": "Lumirise Custom",
				},
			],
			"Warehouse": [
				{
					"fieldname": "lr_rm_location_section",
					"label": "Lumirise RM Barcode Location",
					"fieldtype": "Section Break",
					"insert_after": "warehouse_type",
					"collapsible": 1,
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_location_barcode",
					"label": "Location Barcode",
					"fieldtype": "Data",
					"insert_after": "lr_rm_location_section",
					"in_standard_filter": 1,
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_slot_capacity",
					"label": "Slot Capacity",
					"fieldtype": "Float",
					"insert_after": "lr_location_barcode",
					"description": "Optional quantity capacity. Zero means capacity is not enforced.",
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_slot_capacity_uom",
					"label": "Capacity UOM",
					"fieldtype": "Link",
					"options": "UOM",
					"insert_after": "lr_slot_capacity",
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_slot_status",
					"label": "Slot Status",
					"fieldtype": "Select",
					"options": "Available\nBlocked\nMaintenance",
					"default": "Available",
					"insert_after": "lr_slot_capacity_uom",
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_allowed_item_group",
					"label": "Allowed Item Group",
					"fieldtype": "Link",
					"options": "Item Group",
					"insert_after": "lr_slot_status",
					"module": "Lumirise Custom",
				},
			],
			"Purchase Receipt": [
				{
					"fieldname": "lr_rm_barcode_section",
					"label": "RM Barcode Source",
					"fieldtype": "Section Break",
					"insert_after": "items",
					"collapsible": 1,
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_inbound_logistics",
					"label": "Inbound Logistics",
					"fieldtype": "Link",
					"options": "Inbound Logistics",
					"insert_after": "lr_rm_barcode_section",
					"read_only": 1,
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_iqc",
					"label": "IQC",
					"fieldtype": "Link",
					"options": "IQC",
					"insert_after": "lr_inbound_logistics",
					"read_only": 1,
					"module": "Lumirise Custom",
				},
			],
			"Purchase Receipt Item": [
				{
					"fieldname": "lr_rm_package_refs",
					"label": "RM Package Barcodes",
					"fieldtype": "Small Text",
					"insert_after": "batch_no",
					"read_only": 1,
					"allow_on_submit": 1,
					"module": "Lumirise Custom",
				},
			],
			"Stock Entry": [
				{
					"fieldname": "lr_rm_scan_section",
					"label": "RM Barcode Scanning",
					"fieldtype": "Section Break",
					"insert_after": "items",
					"collapsible": 1,
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_scan_location_barcode",
					"label": "Scanned Location",
					"fieldtype": "Data",
					"insert_after": "lr_rm_scan_section",
					"no_copy": 1,
					"module": "Lumirise Custom",
				},
				{
					"fieldname": "lr_scan_package_barcode",
					"label": "Scanned Package",
					"fieldtype": "Data",
					"insert_after": "lr_scan_location_barcode",
					"no_copy": 1,
					"module": "Lumirise Custom",
				},
			],
			"Stock Entry Detail": [
				{
					"fieldname": "lr_rm_package",
					"label": "RM Package",
					"fieldtype": "Link",
					"options": "RM Receiving Package",
					"insert_after": "batch_no",
					"in_list_view": 1,
					"module": "Lumirise Custom",
				},
			],
		},
		update=True,
	)
	frappe.clear_cache()
