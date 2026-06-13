"""Idempotent workspace setup for the Sales Platform build.

Runs on after_migrate: ensures roles, Item/BOM costing custom fields,
and default Sales Credit Terms exist. Safe to run repeatedly.
"""

import frappe

from lumirise_custom.setup.costing_fields import create_costing_fields
from lumirise_custom.setup.flow_fields import create_flow_fields
from lumirise_custom.setup.production_setup import setup_production_flow
from lumirise_custom.setup.task_seed import seed_task_engine

SALES_PLATFORM_ROLES = ["Pricing Manager", "Sales Approver", "Sales Auditor"]

DEFAULT_CREDIT_TERMS = [
	{"payment_type": "Advance", "credit_days": 0, "percentage": 0},
	{"payment_type": "Credit", "credit_days": 30, "percentage": 1},
	{"payment_type": "Credit", "credit_days": 45, "percentage": 1.5},
	{"payment_type": "Credit", "credit_days": 60, "percentage": 2},
	{"payment_type": "Credit", "credit_days": 75, "percentage": 2.5},
]


def before_migrate():
	"""Roles referenced by DocType JSON permissions must exist before the
	schema sync imports those DocTypes."""
	from lumirise_custom.setup.task_seed import ensure_ops_role

	ensure_ops_role()


def after_migrate():
	ensure_roles()
	create_costing_fields()
	create_flow_fields()
	seed_credit_terms()
	init_settings()
	# Task / Notification / Kanban engine: role, department map, Kanban board.
	seed_task_engine()
	# Line-aware production flow: warehouses, lines, Stock Entry Types, backflush
	# mode, Operations Settings warehouse fields. Runs AFTER task_seed so it owns
	# the production-flow warehouse fields (Shop Floor / Production FG / Dispatch FG
	# / PDI / Rejection) without clashing with the task-seed name-pattern defaults.
	setup_production_flow()


def init_settings():
	"""Single-doctype defaults only apply in the UI; persist them so server
	code reading via get_single_value gets real values."""
	defaults = {
		"no_master_box_extra_cost": 0.8,
		"profit_fallback_finish": "UV DRIPOFF SPOT",
		"approval_window_days": 7,
		"min_agreed_qty": 1000,
	}
	settings = frappe.get_single("Sales Platform Settings")
	changed = False
	for field, value in defaults.items():
		if not settings.get(field):
			settings.set(field, value)
			changed = True
	if changed:
		settings.save(ignore_permissions=True)


def ensure_roles():
	for role in SALES_PLATFORM_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def seed_credit_terms():
	if not frappe.db.exists("DocType", "Sales Credit Term"):
		return
	for term in DEFAULT_CREDIT_TERMS:
		if not frappe.db.exists(
			"Sales Credit Term",
			{"payment_type": term["payment_type"], "credit_days": term["credit_days"]},
		):
			frappe.get_doc(dict(term, doctype="Sales Credit Term")).insert(
				ignore_permissions=True
			)
