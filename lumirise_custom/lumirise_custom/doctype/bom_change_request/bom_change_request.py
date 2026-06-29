# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# BOM Change Request = the controlled, on-system replacement for the verbal
# VJSR/AJSR sign-off. Flow:
#   Draft -> (submit for approval) -> Pending Change Approval
#         -> [Vijay] approve change   -> Pending Cost Approval
#         -> [Ajay]  approve cost      -> Approved  ==> creates a NEW dated BOM
#            version (copy of current + the requested changes), makes it the FG
#            item's default, and records supersession. The old version stays as
#            history. Either approver can Reject.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, nowdate

CHANGE_ROLES = {"Sales Approver", "Manufacturing Manager", "System Manager"}
COST_ROLES = {"MD", "System Manager"}


class BOMChangeRequest(Document):
	def validate(self):
		if self.current_bom and self.fg_item:
			bom_item = frappe.db.get_value("BOM", self.current_bom, "item")
			if bom_item and bom_item != self.fg_item:
				frappe.throw(_("Current BOM {0} is not for FG item {1}.").format(
					self.current_bom, self.fg_item))

	def on_submit(self):
		# Submitting the request = sending it for approval.
		if self.workflow_state in (None, "", "Draft"):
			self.db_set("workflow_state", "Pending Change Approval")


def _has_role(roles):
	return bool(roles & set(frappe.get_roles()))


def _load(docname):
	return frappe.get_doc("BOM Change Request", docname)


@frappe.whitelist()
def approve_change(docname):
	"""Vijay: approve that the change itself is correct."""
	doc = _load(docname)
	if not _has_role(CHANGE_ROLES):
		frappe.throw(_("Only Vijay (Sales Approver / Manufacturing Manager) can approve the change."))
	if doc.workflow_state != "Pending Change Approval":
		frappe.throw(_("This request is not awaiting change approval."))
	doc.db_set("change_approved_by", frappe.session.user)
	doc.db_set("change_approved_on", now_datetime())
	doc.db_set("workflow_state", "Pending Cost Approval")
	return {"workflow_state": "Pending Cost Approval"}


@frappe.whitelist()
def approve_cost(docname):
	"""Ajay: approve the cost impact -> create the new BOM version and release it."""
	doc = _load(docname)
	if not _has_role(COST_ROLES):
		frappe.throw(_("Only Ajay (MD) can approve the cost."))
	if doc.workflow_state != "Pending Cost Approval":
		frappe.throw(_("This request is not awaiting cost approval."))
	new_bom = _create_new_version(doc)
	doc.db_set("cost_approved_by", frappe.session.user)
	doc.db_set("cost_approved_on", now_datetime())
	doc.db_set("new_bom", new_bom)
	doc.db_set("workflow_state", "Approved")
	frappe.msgprint(
		_("Approved. New BOM version {0} created and set as the default for {1}.").format(
			new_bom, doc.fg_item),
		indicator="green", alert=True)
	return {"workflow_state": "Approved", "new_bom": new_bom}


@frappe.whitelist()
def reject(docname, reason=None):
	doc = _load(docname)
	if not (_has_role(CHANGE_ROLES) or _has_role(COST_ROLES)):
		frappe.throw(_("You are not authorised to reject this request."))
	doc.db_set("workflow_state", "Rejected")
	if reason:
		doc.add_comment("Comment", _("Rejected: {0}").format(reason))
	return {"workflow_state": "Rejected"}


def _create_new_version(doc):
	"""Copy the current BOM, apply the requested changes, submit it as a new dated
	version, and make it the FG item's default. Returns the new BOM name."""
	src = frappe.get_doc("BOM", doc.current_bom)
	new = frappe.copy_doc(src)
	new.is_default = 1
	new.is_active = 1

	# index existing rows by item for Remove / Change Qty.
	by_item = {}
	for row in new.items:
		by_item.setdefault(row.item_code, []).append(row)

	to_remove = []
	for ch in doc.changes:
		if ch.action == "Remove":
			for row in by_item.get(ch.item_code, []):
				to_remove.append(row)
		elif ch.action == "Change Qty":
			rows = by_item.get(ch.item_code)
			if not rows:
				frappe.throw(_("Cannot change qty: {0} is not in BOM {1}.").format(
					ch.item_code, doc.current_bom))
			rows[0].qty = flt(ch.new_qty)
		elif ch.action == "Add":
			if by_item.get(ch.item_code):
				frappe.throw(_("Cannot add: {0} is already in BOM {1} (use Change Qty).").format(
					ch.item_code, doc.current_bom))
			new.append("items", {"item_code": ch.item_code, "qty": flt(ch.new_qty) or 1})

	new.items = [r for r in new.items if r not in to_remove]
	if not new.items:
		frappe.throw(_("The change would leave the BOM with no components."))

	# Date-versioning markers (custom fields on BOM, created in setup).
	new.lr_version_date = nowdate()
	new.lr_supersedes = doc.current_bom
	new.lr_change_request = doc.name
	new.flags.from_change_request = True

	new.insert(ignore_permissions=True)
	new.submit()

	# Make it the item default + deactivate the superseded BOM as history.
	frappe.db.set_value("Item", doc.fg_item, "default_bom", new.name)
	try:
		old = frappe.get_doc("BOM", doc.current_bom)
		old.flags.from_change_request = True
		old.db_set("is_default", 0)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "BOM CR: deactivate old default failed")
	return new.name
