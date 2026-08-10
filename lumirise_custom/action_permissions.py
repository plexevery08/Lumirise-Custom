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
