"""Server-side role gates for Lumirise operational actions.

DocType permissions decide who can open and edit a record. These helpers enforce
the narrower business boundary for whitelisted buttons whose consequences cross
departments or move stock.
"""

import frappe
from frappe import _

QUALITY_ACTION_ROLES = frozenset({"Quality Inspector", "Quality Manager", "System Manager"})
LOGISTICS_ACTION_ROLES = frozenset({"Logistics User", "Logistics Manager", "System Manager"})
PURCHASE_RELEASE_ROLES = frozenset({"Purchase User", "Purchase Manager", "Purchase Head", "System Manager"})
SECURITY_ACTION_ROLES = frozenset(
	{"Security User", "Logistics User", "Logistics Manager", "System Manager"}
)
INWARD_MANAGER_ROLES = frozenset({"Logistics Manager", "System Manager"})
STORES_ACCEPTANCE_ROLES = frozenset(
	{"Factory Store Manager", "Stock User", "Stock Manager", "System Manager"}
)


def require_any_role(allowed_roles, message):
	"""Require at least one explicit business role for a whitelisted action."""
	if allowed_roles.isdisjoint(frappe.get_roles()):
		frappe.throw(_(message), frappe.PermissionError)


def require_quality_action():
	require_any_role(QUALITY_ACTION_ROLES, "Only Quality can perform this inspection action.")


def require_logistics_action():
	require_any_role(LOGISTICS_ACTION_ROLES, "Only Logistics can update this consignment movement.")


def require_purchase_release():
	require_any_role(PURCHASE_RELEASE_ROLES, "Only Purchase can release this container.")


def require_security_action():
	require_any_role(
		SECURITY_ACTION_ROLES,
		"Only Security or Logistics can register and verify a vehicle at the gate.",
	)


def require_inward_manager_action():
	require_any_role(
		INWARD_MANAGER_ROLES,
		"Only the Inward / Logistics Manager can approve this inward action.",
	)


def require_stores_acceptance():
	require_any_role(
		STORES_ACCEPTANCE_ROLES,
		"Only RM Stores can accept, verify, or put away inward material.",
	)


def require_document_permission(doctype, name, permission_type="write"):
	"""Require permission on the exact source record, not only its DocType."""
	frappe.has_permission(doctype, permission_type, name, throw=True)


def require_doctype_permissions(doctype, *permission_types):
	"""Require every downstream permission before using elevated framework APIs."""
	for permission_type in permission_types:
		frappe.has_permission(doctype, permission_type, throw=True)


def require_stock_entry_permissions(*, submit=False, cancel=False):
	permissions = [] if cancel and not submit else ["create"]
	if submit:
		permissions.append("submit")
	if cancel:
		permissions.append("cancel")
	require_doctype_permissions("Stock Entry", *permissions)
