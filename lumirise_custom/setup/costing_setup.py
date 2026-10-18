"""One-time/idempotent setup for the authoritative custom-app costing engine."""

import frappe

LEGACY_SERVER_SCRIPTS = (
	"BOM Cost Input Guard",
	"BOM Cost Input Guard (Server Script)",
	"BOM Link Backfill",
	"BOM Link Backfill (Server Script)",
	"BOM Parent Cost Cascade",
	"BOM Parent Cost Cascade (Server Script)",
	"BOM Parent Cost Cascade Submitted",
	"BOM Parent Cost Cascade Submitted (Server Script)",
	"Item BOM Cost Cascade",
	"Item BOM Cost Cascade (Server Script)",
	"Item Cost Input Guard",
	"Item Cost Input Guard (Server Script)",
)

LEGACY_CLIENT_SCRIPTS = (
	"BOM Form Script",
	"BOM (Client Script)",
	"Item Form Script",
	"Item (Client Script)",
)


def setup_costing_system():
	"""Disable only duplicate legacy calculators and queue a normalized rebuild.

	The documents are retained for audit/recovery; they are never deleted.
	"""
	if frappe.db.exists("DocType", "Server Script"):
		for script_name in LEGACY_SERVER_SCRIPTS:
			if frappe.db.exists("Server Script", script_name):
				frappe.db.set_value("Server Script", script_name, "disabled", 1, update_modified=False)

	if frappe.db.exists("DocType", "Client Script"):
		for script_name in LEGACY_CLIENT_SCRIPTS:
			if frappe.db.exists("Client Script", script_name):
				frappe.db.set_value("Client Script", script_name, "enabled", 0, update_modified=False)

	if frappe.db.exists("BOM", {"is_active": 1, "docstatus": 1}):
		from lumirise_custom.costing import schedule_costing_rebuild

		schedule_costing_rebuild()
