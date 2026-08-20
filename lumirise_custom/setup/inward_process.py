"""Auditable fields for the poster-driven material inward process.

The fields live on the existing Inbound Logistics and RM Package records.  Stock
truth remains in native Purchase Receipt and Stock Entry ledgers.

LAYOUT OWNERSHIP (2026-08-11): the 60 Inbound Logistics fields below were moved
into ``inbound_logistics.json`` so the form layout has a single owner.  Inbound
Logistics is a doctype we own, and the owned-doctype rule says its field
properties belong in the JSON, not in a Custom Field overlay — the overlay made
the layout impossible to organise, because ``insert_after`` decides placement and
the whole block could only ever land as one flat run of 56 fields.  The list is
kept here only as the source for ``retire_inbound_custom_fields`` (below), which
deletes the now-redundant Custom Field rows.  Deleting a Custom Field does NOT
drop its database column, so the data on existing records is untouched.

RM Package still uses Custom Fields — that layout is small and fine as-is.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# Superseded by inbound_logistics.json — retained only to drive the retirement
# cleanup. Do NOT re-add these via create_custom_fields; edit the JSON instead.
RETIRED_INBOUND_FIELDS = [
	{
		"fieldname": "lr_inward_process_section",
		"label": "Material Inward Process",
		"fieldtype": "Section Break",
		"insert_after": "current_location",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "inward_stage",
		"label": "Inward Stage",
		"fieldtype": "Select",
		"options": "Vehicle In Transit\nAwaiting Gate Approval\nGate Approved\nGate Verified\nDocuments Verified\nDocument Exception\nIQC Task Raised\nUnloading In Progress\nPhysical Verification\nIQC In Progress\nIQC Failed\nStorage Authorized\nGRN Posted\nPut Away Complete\nDocuments Handed Over\nClosed",
		"default": "Vehicle In Transit",
		"read_only": 1,
		"allow_on_submit": 1,
		"in_list_view": 1,
		"in_standard_filter": 1,
		"insert_after": "lr_inward_process_section",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "arrival_registered_on",
		"label": "Vehicle Arrived On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "inward_stage",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "arrival_registered_by",
		"label": "Arrival Registered By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "arrival_registered_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "manager_notified",
		"label": "Inward Manager Notified",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "arrival_registered_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "gate_stamp_reference",
		"label": "Gate Stamp / Signature Reference",
		"fieldtype": "Data",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "manager_notified",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "gate_invoice_attachment",
		"label": "Gate-stamped Invoice",
		"fieldtype": "Attach",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "gate_stamp_reference",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "gate_verified_by",
		"label": "Gate Verified By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "gate_invoice_attachment",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "gate_verified_on",
		"label": "Gate Verified On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "gate_verified_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "lr_document_checklist_section",
		"label": "Document Handover & Verification",
		"fieldtype": "Section Break",
		"insert_after": "gate_verified_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "invoice_verified",
		"label": "Invoice Received & Verified",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "lr_document_checklist_section",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "packing_list_matched",
		"label": "Packing List Received & Matched",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "invoice_verified",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "waybill_verified",
		"label": "Waybill / LR Received & Verified",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "packing_list_matched",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "other_documents_received",
		"label": "Other Supporting Documents Received",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "waybill_verified",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "documents_forwarded_to_manager",
		"label": "Documents Forwarded to Manager",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "other_documents_received",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "document_bundle_attachment",
		"label": "Inward Document Bundle",
		"fieldtype": "Attach",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "documents_forwarded_to_manager",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "documents_verified_by",
		"label": "Documents Verified By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "document_bundle_attachment",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "documents_verified_on",
		"label": "Documents Verified On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "documents_verified_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "iqc_task",
		"label": "IQC Task (Bitrix Mirror Source)",
		"fieldtype": "Link",
		"options": "Lumirise Task",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "documents_verified_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "iqc_reference",
		"label": "Incoming Quality Control",
		"fieldtype": "Link",
		"options": "IQC",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "iqc_task",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "iqc_task_raised_by",
		"label": "IQC Task Raised By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "iqc_reference",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "iqc_task_raised_on",
		"label": "IQC Task Raised On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "iqc_task_raised_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "lr_unloading_section",
		"label": "Unloading & Physical Verification",
		"fieldtype": "Section Break",
		"insert_after": "iqc_task_raised_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "unloading_status",
		"label": "Unloading Status",
		"fieldtype": "Select",
		"options": "Pending\nIn Progress\nCompleted\nBlocked",
		"default": "Pending",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "lr_unloading_section",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "unloading_started_by",
		"label": "Unloading Started By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "unloading_status",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "unloading_started_on",
		"label": "Unloading Started On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "unloading_started_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "unloading_completed_by",
		"label": "Unloading Completed By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "unloading_started_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "unloading_completed_on",
		"label": "Unloading Completed On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "unloading_completed_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "physical_verification_status",
		"label": "Packing-list Quantity Check",
		"fieldtype": "Select",
		"options": "Pending\nMatched\nShort Quantity\nExcess Quantity\nDamaged Material\nTransport Damage\nMultiple Exceptions",
		"default": "Pending",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "unloading_completed_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "physical_verification_remarks",
		"label": "Physical Verification Remarks",
		"fieldtype": "Small Text",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "physical_verification_status",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "physical_verified_by",
		"label": "Physical Quantity Verified By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "physical_verification_remarks",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "physical_verified_on",
		"label": "Physical Quantity Verified On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "physical_verified_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "invoice_price_verified",
		"label": "Invoice Price Checked Against PO",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "physical_verified_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "price_verified_by",
		"label": "Price Verified By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "invoice_price_verified",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "price_verified_on",
		"label": "Price Verified On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "price_verified_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "inward_exceptions",
		"label": "Quantity / Damage Exceptions",
		"fieldtype": "Table",
		"options": "Inbound Process Exception",
		"allow_on_submit": 1,
		"insert_after": "price_verified_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "lr_storage_section",
		"label": "Storage, GRN & Final Sign-off",
		"fieldtype": "Section Break",
		"insert_after": "inward_exceptions",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "rack_warehouse",
		"label": "Allocated Rack / Bay",
		"fieldtype": "Link",
		"options": "Warehouse",
		"allow_on_submit": 1,
		"insert_after": "lr_storage_section",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "rack_allocated_by",
		"label": "Rack Allocated By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "rack_warehouse",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "rack_allocated_on",
		"label": "Rack Allocated On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "rack_allocated_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "storage_authorized",
		"label": "Storage Authorized",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "rack_allocated_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "storage_authorized_by",
		"label": "Storage Authorized By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "storage_authorized",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "storage_authorized_on",
		"label": "Storage Authorized On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "storage_authorized_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "purchase_receipt",
		"label": "GRN / Purchase Receipt",
		"fieldtype": "Link",
		"options": "Purchase Receipt",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "storage_authorized_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "outward_accepted",
		"label": "RM / Outward Team Physical Count Accepted",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "purchase_receipt",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "outward_accepted_by",
		"label": "Accepted By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "outward_accepted",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "outward_accepted_on",
		"label": "Accepted On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "outward_accepted_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "signed_packing_list",
		"label": "Signed Packing List",
		"fieldtype": "Attach",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "outward_accepted_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "stock_note_reference",
		"label": "Rack Stock Note Reference",
		"fieldtype": "Data",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "signed_packing_list",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "stock_note_attachment",
		"label": "Rack Stock Note",
		"fieldtype": "Attach",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "stock_note_reference",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "erp_entry_verified",
		"label": "ERP Stock Entry Cross-checked",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "stock_note_attachment",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "erp_verified_by",
		"label": "ERP Entry Verified By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "erp_entry_verified",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "erp_verified_on",
		"label": "ERP Entry Verified On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "erp_verified_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "documents_handed_over",
		"label": "GRN / Invoice / Waybill / IQC Handed to Purchase",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "erp_verified_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "documents_handed_over_by",
		"label": "Documents Handed Over By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "documents_handed_over",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "documents_handed_over_on",
		"label": "Documents Handed Over On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "documents_handed_over_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "handover_bundle_attachment",
		"label": "Purchase Handover Bundle",
		"fieldtype": "Attach",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "documents_handed_over_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "final_signoff",
		"label": "Final Inward Sign-off",
		"fieldtype": "Check",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "handover_bundle_attachment",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "final_signed_off_by",
		"label": "Final Sign-off By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "final_signoff",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "final_signed_off_on",
		"label": "Final Sign-off On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"allow_on_submit": 1,
		"insert_after": "final_signed_off_by",
		"module": "Lumirise Custom",
	},
]


PACKAGE_FIELDS = [
	{
		"fieldname": "lr_label_section",
		"label": "Physical Label Control",
		"fieldtype": "Section Break",
		"insert_after": "last_stock_entry",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "label_printed",
		"label": "Label Printed",
		"fieldtype": "Check",
		"read_only": 1,
		"insert_after": "lr_label_section",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "label_printed_by",
		"label": "Printed By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"insert_after": "label_printed",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "label_printed_on",
		"label": "Printed On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"insert_after": "label_printed_by",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "label_applied",
		"label": "Label Applied to Carton / Pallet",
		"fieldtype": "Check",
		"read_only": 1,
		"insert_after": "label_printed_on",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "label_applied_by",
		"label": "Applied By",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"insert_after": "label_applied",
		"module": "Lumirise Custom",
	},
	{
		"fieldname": "label_applied_on",
		"label": "Applied On",
		"fieldtype": "Datetime",
		"read_only": 1,
		"insert_after": "label_applied_by",
		"module": "Lumirise Custom",
	},
]


def retire_inbound_custom_fields():
	"""Delete the Inbound Logistics Custom Fields now defined in the doctype JSON.

	Idempotent. Only removes a Custom Field when the JSON actually carries the
	same fieldname, so a half-migrated bench can never end up with the field
	missing from both places. Deleting a Custom Field leaves its database column
	intact (``CustomField.on_trash`` drops property setters and layouts, never
	the column), so field data on existing records survives.
	"""
	if not frappe.db.exists("DocType", "Inbound Logistics"):
		return

	# Read the JSON-defined fieldnames straight off the DocType record — not off
	# the merged meta, which would still include the Custom Fields themselves.
	json_fields = set(
		frappe.get_all(
			"DocField",
			filters={"parent": "Inbound Logistics", "parenttype": "DocType"},
			pluck="fieldname",
		)
	)
	if not json_fields:
		return

	retired = 0
	for spec in RETIRED_INBOUND_FIELDS:
		fieldname = spec["fieldname"]
		if fieldname not in json_fields:
			# JSON has not been synced yet — leave the overlay in place.
			continue
		name = frappe.db.get_value(
			"Custom Field", {"dt": "Inbound Logistics", "fieldname": fieldname}, "name"
		)
		if name:
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
			retired += 1

	# The section breaks the old overlay created are gone from the JSON entirely
	# (their groupings were rebuilt as tabs/sections), so sweep any leftover
	# Custom Field rows for them too.
	for orphan in ("lr_inward_process_section", "lr_document_checklist_section",
	               "lr_unloading_section", "lr_storage_section"):
		name = frappe.db.get_value(
			"Custom Field", {"dt": "Inbound Logistics", "fieldname": orphan}, "name"
		)
		if name:
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
			retired += 1

	if retired:
		frappe.clear_cache(doctype="Inbound Logistics")

	return retired


def create_inward_process_fields():
	create_custom_fields({"RM Package": PACKAGE_FIELDS}, update=True)
	retire_inbound_custom_fields()
	# ``exceptions`` is a framework-level attribute name and is not accepted as
	# a Custom Field fieldname on every Frappe version. Preserve any rows created
	# by an earlier local build while moving them to the durable fieldname.
	if frappe.db.exists("DocType", "Inbound Process Exception"):
		frappe.db.sql(
			"""update `tabInbound Process Exception`
			set parentfield = 'inward_exceptions'
			where parentfield = 'exceptions'"""
		)
