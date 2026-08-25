"""Record-level visibility for the read-only Lumirise task queues.

Task queues must use the same permission boundary as the underlying DocType:
ordinary users see tasks assigned to them (or their supervisor/HOD fields),
while control users may review the full operational queue.  This keeps the
read-only UI useful without making a new global task-sharing mechanism.
"""

import frappe


CONTROL_ROLES = frozenset({"System Manager", "Lumirise Operations"})


def _is_control_user(user: str) -> bool:
	return bool(CONTROL_ROLES & set(frappe.get_roles(user)))


def get_permission_query_conditions(user: str | None = None) -> str | None:
	user = user or frappe.session.user
	if _is_control_user(user):
		return None

	escaped = frappe.db.escape(user, percent=False)
	return (
		f"(`tabLumirise Task`.`owner_user` = {escaped} "
		f"or `tabLumirise Task`.`supervisor_user` = {escaped} "
		f"or `tabLumirise Task`.`hod_user` = {escaped} "
		f"or `tabLumirise Task`.`owner` = {escaped})"
	)


def has_permission(doc, ptype: str = "read", user: str | None = None) -> bool | None:
	user = user or frappe.session.user
	if _is_control_user(user):
		return True
	if ptype in {"read", "select", "report", "export", "print"}:
		return user in {doc.owner_user, doc.supervisor_user, doc.hod_user, doc.owner}
	if ptype == "write":
		return user in {doc.owner_user, doc.supervisor_user}
	return False

