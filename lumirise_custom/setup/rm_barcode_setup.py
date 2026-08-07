"""Idempotent non-destructive setup for the RM barcode subsystem."""

import frappe


def setup_rm_barcode_system():
	if not frappe.db.exists("Stock Entry Type", "RM Package Put Away"):
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"__newname": "RM Package Put Away",
				"purpose": "Material Transfer",
				"is_standard": 0,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("DocType", "Lumirise Operations Settings"):
		return
	settings = frappe.get_single("Lumirise Operations Settings")
	changed = False
	# The UI is enabled after migrate. Enforcement remains OFF until opening stock
	# has package labels and the UAT checklist is signed off.
	if settings.get("enable_rm_barcode_system") is None:
		settings.enable_rm_barcode_system = 1
		changed = True
	if settings.get("enforce_rm_package_scan") is None:
		settings.enforce_rm_package_scan = 0
		changed = True
	if changed:
		settings.save(ignore_permissions=True)
