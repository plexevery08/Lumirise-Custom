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
  - lr_consignee_bom_ref  : read-only Data (2026-08-22, Rishitha's follow-up: "can you do
                            that with child BOMs... it would be easier for us to track").
                            The linked Subcontracting Order's child BOM(s) / semi-finished
                            item(s) this drop-shipped RM is destined to become -- e.g.
                            "BOM-P128-001 -> P128". Resolved the same moment as
                            lr_consignee_sco_ref, so Store/the RM-Conversion approver see
                            it right on the PO, not just buried in the Subcontracting
                            Order. (The Send-to-Subcontractor Stock Entry itself already
                            carries bom_no/subcontracted_item natively per row -- this
                            field is what was missing at the PO/Consignee stage.)
  - lr_consignee_address  : Link -> Address, the consignee vendor's own ship-to address
                            (2026-08-21 correction: NOT the native `shipping_address`
                            field -- AccountsController.validate_company_linked_addresses()
                            hard-requires shipping_address to belong to the Company on
                            every Purchase Order save, unconditionally, unless ERPNext's
                            own `delivered_by_supplier` ship-to-CUSTOMER drop-ship flag is
                            set -- a different feature we should not repurpose. A plain
                            custom field sidesteps that validation entirely.
  - lr_consignee_address_display : read-only Text Editor, the formatted address text.
                            Same Link+display pairing ERPNext itself uses for every other
                            address on this doctype (shipping_address/shipping_address_display,
                            dispatch_address/dispatch_address_display) -- purchase_order.js
                            populates it the same way, via erpnext.utils.get_address_display().
                            MUST be Text Editor, not Small Text: get_address_display()
                            always returns HTML (<br> line breaks) -- Small Text has no HTML
                            renderer and shows the tags literally (bug found 2026-08-22).

Both address fields live in the standard "Address & Contact" tab (2026-08-22, moved out
of the top supplier section per Riddhi), in their own section that only appears once a
Consignee is set.

Idempotent -- safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def create_dropship_fields():
	# Custom Field only recomputes its idx from insert_after for a brand-new doc
	# (custom_field.py::validate -- `if self.is_new() or self.insert_after == "append"`).
	# lr_consignee_address previously lived in the top supplier section; moving it into
	# the Address & Contact tab means changing insert_after on an EXISTING field, which
	# on_update alone would silently keep the old position. Drop it first so the create
	# below is a fresh insert and actually lands in the new spot.
	old_insert_after = frappe.db.get_value(
		"Custom Field", {"dt": "Purchase Order", "fieldname": "lr_consignee_address"}, "insert_after"
	)
	if old_insert_after and old_insert_after != "billing_address_display":
		frappe.delete_doc(
			"Custom Field", "Purchase Order-lr_consignee_address", ignore_permissions=True, force=True
		)

	# Small Text -> Text Editor isn't in Frappe's ALLOWED_FIELDTYPE_CHANGE groups (would
	# throw "Fieldtype cannot be changed"), so the same drop-and-recreate trick applies.
	# Underlying column is text-compatible either way -- data (the HTML string) survives.
	old_fieldtype = frappe.db.get_value(
		"Custom Field", {"dt": "Purchase Order", "fieldname": "lr_consignee_address_display"}, "fieldtype"
	)
	if old_fieldtype and old_fieldtype != "Text Editor":
		frappe.delete_doc(
			"Custom Field", "Purchase Order-lr_consignee_address_display",
			ignore_permissions=True, force=True,
		)

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
			fieldname="lr_consignee_bom_ref",
			label="Child BOM / Semi-Finished Item",
			fieldtype="Data",
			insert_after="lr_consignee_sco_ref",
			read_only=1,
			module="Lumirise Custom",
			description="Auto-filled from the linked Subcontracting Order: which child BOM "
			"and semi-finished item this drop-shipped RM is destined to become "
			"(e.g. \"BOM-P128-001 -> P128\"). Rishitha's follow-up ask, 2026-08-22 -- "
			"traceability for the vendor-to-vendor consignee flow, not just the return leg.",
		),
		dict(
			fieldname="lr_consignee_address_section",
			label="Consignee Ship-To Address (Vendor-to-Vendor Drop-Ship)",
			fieldtype="Section Break",
			insert_after="billing_address_display",
			depends_on="eval:doc.lr_consignee",
			module="Lumirise Custom",
		),
		dict(
			fieldname="lr_consignee_address",
			label="Consignee Ship-To Address",
			fieldtype="Link",
			options="Address",
			insert_after="lr_consignee_address_section",
			module="Lumirise Custom",
			description="The Consignee vendor's own address to print on the PO, telling "
			"the supplier's dispatch team where to send it. NOT the native Shipping "
			"Address field -- that must stay a Company address (ERPNext's own hard rule); "
			"this field exists specifically so it doesn't have to.",
		),
		dict(
			fieldname="lr_consignee_address_cb",
			fieldtype="Column Break",
			insert_after="lr_consignee_address",
			module="Lumirise Custom",
		),
		dict(
			fieldname="lr_consignee_address_display",
			label="Consignee Address Details",
			fieldtype="Text Editor",
			insert_after="lr_consignee_address_cb",
			read_only=1,
			module="Lumirise Custom",
			description="Auto-filled from the address above -- same pairing ERPNext uses for "
			"Shipping/Dispatch/Billing Address on this form.",
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
