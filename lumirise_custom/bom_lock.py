# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# BOM version-lock. Once a Work Order is raised against a BOM, the floor is
# building off it, so it must not silently change. We:
#   - mark the BOM lr_locked on Work Order submit, and
#   - block deactivating / un-defaulting a locked BOM unless the change comes
#     from the sanctioned BOM Change Request path (which creates a NEW version
#     instead of mutating the live one).

import frappe
from frappe import _
from frappe.utils import nowdate


def lock_bom_on_work_order(doc, method=None):
	"""Work Order on_submit: lock its BOM (fail-safe, never blocks the WO)."""
	try:
		bom = doc.get("bom_no")
		if not bom or not frappe.db.exists("BOM", bom):
			return
		updates = {"lr_locked": 1}
		if not frappe.db.get_value("BOM", bom, "lr_version_date"):
			updates["lr_version_date"] = frappe.db.get_value("BOM", bom, "creation") or nowdate()
		frappe.db.set_value("BOM", bom, updates, update_modified=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "bom_lock: lock_bom_on_work_order failed")


def guard_bom_change(doc, method=None):
	"""BOM validate: keep a locked, live BOM from being deactivated / un-defaulted
	outside a BOM Change Request. Narrow on purpose so cost auto-refresh (which
	uses db_set, not save) is never affected."""
	if doc.is_new() or getattr(doc.flags, "from_change_request", False):
		return
	if not doc.get("lr_locked"):
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	# Block turning a locked BOM inactive or removing its default status directly.
	if before.is_active and not doc.is_active:
		frappe.throw(_(
			"BOM {0} is locked (a Work Order is building from it). Raise a BOM "
			"Change Request to create a new version instead of deactivating it."
		).format(doc.name))
	if before.is_default and not doc.is_default:
		frappe.throw(_(
			"BOM {0} is the locked default. Change it through a BOM Change Request."
		).format(doc.name))
