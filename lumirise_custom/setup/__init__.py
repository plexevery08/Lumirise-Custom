"""Idempotent workspace setup for the Sales Platform build.

Runs on after_migrate: ensures roles, Item/BOM costing custom fields,
and default Sales Credit Terms exist. Safe to run repeatedly.
"""

import frappe

from lumirise_custom.setup.costing_fields import create_costing_fields
from lumirise_custom.setup.flow_fields import create_flow_fields
from lumirise_custom.setup.bom_fields import create_bom_fields
from lumirise_custom.setup.purchase_reco_fields import create_purchase_reco_fields
from lumirise_custom.setup.wo_line_transfer_fields import create_wo_line_transfer_fields
from lumirise_custom.setup.purchase_plan_supplier_fields import create_purchase_plan_supplier_fields
from lumirise_custom.setup.production_setup import setup_production_flow
from lumirise_custom.setup.task_seed import seed_task_engine
from lumirise_custom.setup.approval_setup import setup_approvals

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
	from lumirise_custom.setup.approval_setup import ensure_approval_roles

	ensure_ops_role()
	# Planning Manager / Purchase Head / MD / Factory Store Manager must exist before
	# the workflows that reference them (and the new DocType JSON perms) are imported.
	ensure_approval_roles()


def after_migrate():
	ensure_roles()
	create_costing_fields()
	create_flow_fields()
	create_bom_fields()
	# BOM Reconciliation tab (Tab Break + HTML) on the Purchase Order.
	create_purchase_reco_fields()
	# Line Transfer tab (Tab Break + HTML) on the Work Order — per-line qty breakdown.
	create_wo_line_transfer_fields()
	# Purchase Plan: parent Global Supplier (cascades to lines) + supplier-wise split.
	create_purchase_plan_supplier_fields()
	# Lumirise Traceability panel (SO / Indent / WO / PO refs) on the standard chain
	# doctypes. The custom chain doctypes carry the same four fields in their JSON.
	from lumirise_custom.setup.traceability_fields import create_traceability_fields
	create_traceability_fields()
	# Purchase Invoice: GRN Date field (auto-filled from the linked Purchase Receipt).
	from lumirise_custom.setup.purchase_invoice_fields import create_purchase_invoice_fields
	create_purchase_invoice_fields()

	from lumirise_custom.setup.sales_po_fields import create_sales_po_fields
	create_sales_po_fields()
	# Small UI tweaks (Sai walkthrough): field hides / read-only as Property Setters.
	from lumirise_custom.setup.ui_tweaks import apply_ui_tweaks
	apply_ui_tweaks()
	seed_credit_terms()
	init_settings()
	# Task / Notification / Kanban engine: role, department map, Kanban board.
	seed_task_engine()
	# Line-aware production flow: warehouses, lines, Stock Entry Types, backflush
	# mode, Operations Settings warehouse fields. Runs AFTER task_seed so it owns
	# the production-flow warehouse fields (Shop Floor / Production FG / Dispatch FG
	# / PDI / Rejection) without clashing with the task-seed name-pattern defaults.
	setup_production_flow()
	# Ajay review 2026-06-14: Indent -> Planning Manager approval (not Purchase
	# Manager); Purchase Order -> Purchase Head release approval. Runs last and
	# upserts both workflows so the desired shape is reasserted every migrate.
	setup_approvals()
	# Daily self-test: dashboard Number Card (the Workspace shortcut + reports
	# ship as files/fixtures; Number Cards do not).
	setup_health_check()
	# Quality: seed the 17-parameter defect master (A/B/C class) that drives the
	# AQL engine and the IQC / Customer PDI reject-reason link.
	seed_defect_master()
	# Quality: seed native QI Parameters + RM-incoming / FG-in-house templates.
	seed_quality_inspection_templates()


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


def setup_health_check():
	"""Idempotent: ensure the Health dashboard Number Card exists. Safe to run
	repeatedly; never breaks the migrate if the card cannot be created."""
	try:
		if not frappe.db.exists("DocType", "Health Check Run"):
			return
		label = "Health: Red Runs"
		if not frappe.db.exists("Number Card", {"label": label}):
			frappe.get_doc(
				{
					"doctype": "Number Card",
					"label": label,
					"module": "Lumirise Custom",
					"type": "Document Type",
					"document_type": "Health Check Run",
					"function": "Count",
					"is_public": 1,
					"show_percentage_stats": 0,
					"filters_json": frappe.as_json(
						[["Health Check Run", "overall_status", "=", "Red", False]]
					),
					"color": "#e24c4c",
				}
			).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "setup_health_check failed")


def seed_defect_master():
	"""Idempotent: insert the seed Lumirise Defect Codes (QA edits in-place)."""
	try:
		if not frappe.db.exists("DocType", "Lumirise Defect Code"):
			return
		from lumirise_custom.lumirise_custom.doctype.lumirise_defect_code.lumirise_defect_code import (
			seed_defect_codes,
		)
		seed_defect_codes()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "seed_defect_master failed")


def seed_quality_inspection_templates():
	"""Idempotent: seed native QI Parameters + the two Lumirise QI templates."""
	try:
		from lumirise_custom.setup.quality_setup import seed_quality_templates
		seed_quality_templates()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "seed_quality_inspection_templates failed")


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
