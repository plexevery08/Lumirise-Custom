"""Vendor-to-vendor consignee (Rishitha call, 2026-08-17).

Emergency-only RM drop-ship: a Purchase Order to the RM vendor whose material never
physically reaches Lumirise -- it ships straight to a job-work subcontractor. See
outputs/2026-08-17-consignee-vendor-to-vendor-proposed-solution.md for the full design.

  - lr_consignee          : Link -> Supplier. Blank = normal (ships to Lumirise).
                            Set = this PO's material goes straight to that vendor.
  - lr_consignee_sco_ref  : read-only Data (Rule 1 -- no reverse Link) stamping which
                            open Subcontracting Order this drop-ship is for, so the
                            eventual "Send to Subcontractor" transfer credits the right
                            job (Rishitha: "these two are not connected... if you make
                            these two connected, it would be really easy").
  - lr_consignee_address  : Link -> Address, the consignee vendor's own ship-to address
                            (2026-08-21 correction: NOT the native `shipping_address`
                            field -- AccountsController.validate_company_linked_addresses()
                            hard-requires shipping_address to belong to the Company on
                            every Purchase Order save, unconditionally, unless ERPNext's
                            own `delivered_by_supplier` ship-to-CUSTOMER drop-ship flag is
                            set -- a different feature we should not repurpose. A plain
                            custom field sidesteps that validation entirely.

Idempotent -- safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def create_dropship_fields():
	fields = [
		dict(
			fieldname="lr_consignee",
			label="Consignee (ship straight to this vendor instead of Lumirise)",
			fieldtype="Link",
			options="Supplier",
			insert_after="lr_indent_refs",
			module="Lumirise Custom",
			description="Emergency-only vendor-to-vendor drop-ship. Leave blank for the "
			"normal case (material comes to Lumirise). Set to another vendor and this "
			"PO's RM ships directly to them instead.",
		),
		dict(
			fieldname="lr_consignee_sco_ref",
			label="Consignee's Subcontracting Order",
			fieldtype="Data",
			insert_after="lr_consignee",
			read_only=1,
			module="Lumirise Custom",
			description="Auto-filled: the open Subcontracting Order this drop-shipped RM "
			"is for. Resolved when Consignee is set; pick manually if the vendor has more "
			"than one open job.",
		),
		dict(
			fieldname="lr_consignee_address",
			label="Consignee Ship-To Address",
			fieldtype="Link",
			options="Address",
			insert_after="lr_consignee_sco_ref",
			module="Lumirise Custom",
			description="The Consignee vendor's own address to print on the PO, telling "
			"the supplier's dispatch team where to send it. NOT the native Shipping "
			"Address field -- that must stay a Company address (ERPNext's own hard rule); "
			"this field exists specifically so it doesn't have to.",
		),
	]
	create_custom_fields({"Purchase Order": fields}, update=True)


def ensure_rm_conversion_approver_permission():
	"""Factory Store Manager is the RM-Conversion checkpoint approver (events.py::
	rm_conversion_checkpoint) but has no native Stock Entry permission at all (only
	Stock User / Stock Manager / Manufacturing User / Manufacturing Manager ship
	with submit=1 on Stock Entry) -- without this, the checkpoint's own approver
	role couldn't clear its own gate. Additive: setup_custom_perms() preserves every
	existing role's permissions, this just adds one more row.
	"""
	from frappe.permissions import setup_custom_perms

	role = "Factory Store Manager"
	if frappe.db.get_value("Custom DocPerm", {"parent": "Stock Entry", "role": role, "permlevel": 0}):
		return
	setup_custom_perms("Stock Entry")
	frappe.get_doc({
		"doctype": "Custom DocPerm",
		"parent": "Stock Entry",
		"parenttype": "DocType",
		"parentfield": "permissions",
		"role": role,
		"permlevel": 0,
		"read": 1,
		"write": 1,
		"submit": 1,
	}).insert(ignore_permissions=True)
