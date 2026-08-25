"""Fail-closed rollout controls for the reversible ERPNext UI.

The named flags are the shared contract for the standalone UI. Read visibility
and mutation are separate so safe queues can be observed without granting an
action path; the reviewed draft pilot and task transitions are independently
gated, while scanner mutations remain disabled by default.
"""

import frappe
from frappe import _
from frappe.utils import cint

SETTINGS_DOCTYPE = "Lumirise Operations Settings"

READ_SURFACE_FLAGS = frozenset(
	{
		"easy_ui_role_workspaces",
		"easy_ui_my_work",
		"easy_ui_needs_attention",
		"easy_ui_order_360",
		"easy_ui_material_360",
		"easy_ui_stock_control",
		"easy_ui_quality_queue",
	}
)

ACTION_FLAGS = frozenset(
	{
		"easy_ui_state_actions",
		"easy_ui_scanner_actions",
	}
)

KNOWN_FLAGS = READ_SURFACE_FLAGS | ACTION_FLAGS


def is_enabled(flag: str) -> bool:
	"""Return a named flag's value, failing closed for unknown/absent fields."""
	if flag not in KNOWN_FLAGS:
		return False

	meta = frappe.get_meta(SETTINGS_DOCTYPE)
	if not meta.has_field(flag):
		return False

	return bool(cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, flag) or 0))


def require_enabled(flag: str) -> None:
	"""Reject a disabled surface before any later UI endpoint does work."""
	if flag not in KNOWN_FLAGS:
		frappe.throw(_("Unknown Lumirise UI feature flag: {0}").format(flag), frappe.ValidationError)
	if not is_enabled(flag):
		frappe.throw(_("This Lumirise UI feature is disabled."), frappe.PermissionError)


def all_flags() -> dict[str, bool]:
	"""Return a deterministic snapshot useful for release and rollback checks."""
	return {flag: is_enabled(flag) for flag in sorted(KNOWN_FLAGS)}
