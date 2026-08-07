"""Idempotent fields for barcode-controlled inbound and RM locations."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


FIELDS = {
	"Batch": [
		{"fieldname": "lr_supplier_lot", "label": "Supplier Lot / Reference", "fieldtype": "Data", "insert_after": "supplier", "module": "Lumirise Custom"},
		{"fieldname": "lr_inbound_logistics", "label": "Inbound Logistics", "fieldtype": "Link", "options": "Inbound Logistics", "insert_after": "lr_supplier_lot", "module": "Lumirise Custom"},
		{"fieldname": "lr_iqc_status", "label": "IQC Trace Status", "fieldtype": "Select", "options": "Pending IQC\nPassed\nRejected\nOn Hold\nMoved to RM", "insert_after": "lr_inbound_logistics", "module": "Lumirise Custom"},
	],
	"Warehouse": [
		{"fieldname": "lr_location_barcode", "label": "Location Barcode", "fieldtype": "Data", "unique": 1, "in_list_view": 1, "insert_after": "warehouse_name", "module": "Lumirise Custom"},
		{"fieldname": "lr_location_status", "label": "Location Status", "fieldtype": "Select", "options": "Available\nBlocked\nMaintenance", "default": "Available", "insert_after": "lr_location_barcode", "module": "Lumirise Custom"},
		{"fieldname": "lr_slot_capacity", "label": "Slot Capacity", "fieldtype": "Float", "insert_after": "lr_location_status", "module": "Lumirise Custom"},
		{"fieldname": "lr_allowed_item_group", "label": "Allowed Item Group", "fieldtype": "Link", "options": "Item Group", "insert_after": "lr_slot_capacity", "module": "Lumirise Custom"},
	],
	"Purchase Receipt": [
		{"fieldname": "lr_inbound_logistics", "label": "Inbound Logistics", "fieldtype": "Link", "options": "Inbound Logistics", "insert_after": "supplier_delivery_note", "module": "Lumirise Custom"},
		{"fieldname": "lr_iqc", "label": "IQC", "fieldtype": "Link", "options": "IQC", "insert_after": "lr_inbound_logistics", "module": "Lumirise Custom"},
		{"fieldname": "lr_package_labels_verified", "label": "Package Labels Verified", "fieldtype": "Check", "description": "Confirm all carton/pallet packages have an RM Package barcode before final put-away.", "insert_after": "lr_iqc", "module": "Lumirise Custom"},
	],
	"Stock Entry": [
		{"fieldname": "lr_scan_package", "label": "Scanned RM Package / LPN", "fieldtype": "Data", "insert_after": "scan_barcode", "module": "Lumirise Custom"},
		{"fieldname": "lr_scan_source_location", "label": "Scanned Source Location", "fieldtype": "Link", "options": "Warehouse", "insert_after": "lr_scan_package", "module": "Lumirise Custom"},
		{"fieldname": "lr_scan_verified", "label": "Barcode Scan Verified", "fieldtype": "Check", "read_only": 1, "insert_after": "lr_scan_source_location", "module": "Lumirise Custom"},
	],
}


def create_barcode_flow_fields():
	create_custom_fields(FIELDS, update=True)
