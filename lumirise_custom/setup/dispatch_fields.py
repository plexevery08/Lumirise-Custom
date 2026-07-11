"""Packing-approval fields on the STANDARD Delivery Note (WP-3.4).

A flag-gated packing sign-off before dispatch. Two read-only fields set by the
Approve Packing action; the packing_gate (before_submit) enforces them only when
Lumirise Operations Settings.require_packing_approval is ON. Deliberately NOT a Frappe
Workflow on Delivery Note — a workflow governs every DN the moment it exists, and the
client has not yet decided packing approval is wanted; this stays fully inert until the
flag is turned on.

Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

DN_FIELDS = [
	dict(
		fieldname="lr_packing_approved",
		label="Packing Approved",
		fieldtype="Check",
		insert_after="customer",
		read_only=1,
		allow_on_submit=1,
		no_copy=1,
		module="Lumirise Custom",
	),
	dict(
		fieldname="lr_packing_approved_by",
		label="Packing Approved By",
		fieldtype="Link",
		options="User",
		insert_after="lr_packing_approved",
		read_only=1,
		allow_on_submit=1,
		no_copy=1,
		module="Lumirise Custom",
	),
]


def create_dispatch_fields():
	create_custom_fields({"Delivery Note": DN_FIELDS}, update=True)
