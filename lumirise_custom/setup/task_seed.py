"""Idempotent seed for the Lumirise task / Kanban engine.

Runs on after_migrate. Creates:
  * the "Lumirise Operations" role (give it to every department login),
  * the Lumirise Department Map rows (Supervisor + HOD names from the discovery
    transcripts — User links left blank for the admin to fill in),
  * the public "Lumirise Operations" Kanban board grouped by status.

Everything here is safe to run repeatedly.
"""

import frappe

OPS_ROLE = "Lumirise Operations"

# Department -> (HOD name, Supervisor name, description). Names are from the
# 2026-05/06 department discovery calls. The admin maps these to real ERPNext
# logins via the Lumirise Department Map's User fields once accounts exist.
DEPARTMENTS = [
	("Sales", "Vijay / DJ (Head of Sales)", "Sales Coordinator",
	 "Quotation -> Sales Order, price control, SO approval chain."),
	("Purchase", "MD Ajay (final authorize / PO rates)", "Purchase Manager (Rishitha)",
	 "Indent approval, consolidated PO, vendor price books, subcontracting."),
	("Accounts", "Accounts Manager", "Mohan (Accountant)",
	 "Purchase/sales entries, debit & credit notes, GST/TDS, valuation, aging."),
	("Stores - RM", "Praveen (Head of RM Stores)", "Baswan (RM ERP Manager)",
	 "GRN, IQC gate, rack/bin put-away, material issue, stock accuracy."),
	("Planning - PPC", "Satya (PPC Owner)", "Planning Desk",
	 "SO netting, Material Planning post, Work Order + Indent generation, line allocation."),
	("Quality - PDI/IQC", "Pichai (Head of Quality & PDI)", "Ishaq (IQC) / Kowsalya (PDI)",
	 "Vendor PDI, IQC sampling, customer PDI, rejection traceability."),
	("BOM Engineering", "Sai Krishna (BOM Lead)", "BOM Team",
	 "BOM creation & versioning, Lumerize master copy, sub-BOMs."),
	("Production", "Production Head", "Line Supervisor",
	 "Work order execution, per-line build, hourly counts, FG receipt."),
	("FG Stores - Dispatch", "Suresh Didla (FG Stores)", "FG / Dispatch Team",
	 "FG receipt vs voucher, packing, sample/PDI transfers, dispatch."),
	("Logistics", "Karthik (Logistics)", "Logistics Desk",
	 "Vendor PDI logistics, container/import tracking, vehicle, POD."),
	("Subcontracting", "Yogesh Jain (Subcontracting)", "Subcontracting Desk",
	 "Subcontract orders, job DC tracking (DC-closed), labour PO/invoice."),
]

KANBAN_BOARD = "Lumirise Operations"
KANBAN_COLUMNS = [
	("Open", "Gray"),
	("In Progress", "Blue"),
	("Blocked", "Orange"),
	("Done", "Green"),
	("Cancelled", "Red"),
]


def seed_task_engine():
	ensure_ops_role()
	seed_departments()
	seed_kanban_board()
	seed_operations_settings()


def seed_operations_settings():
	"""Best-effort default for Lumirise Operations Settings so the flow works out
	of the box. These are editable defaults (data), not hard-coded logic — the
	admin confirms/overrides them in the Settings form. Warehouses are matched
	dynamically by name pattern, not pinned to a fixed warehouse."""
	if not frappe.db.exists("DocType", "Lumirise Operations Settings"):
		return
	import erpnext

	s = frappe.get_single("Lumirise Operations Settings")
	changed = False
	if not s.company:
		s.company = erpnext.get_default_company()
		changed = True
	# (settings field, warehouse-name pattern)
	# NOTE: fg_warehouse / dispatch_fg / shop_floor / pdi / rejection are owned by
	# setup.production_setup (the line-aware flow), which runs after this. Here we
	# only seed the unambiguous RM + fallback-WIP defaults.
	for field, pattern in [
		("rm_warehouse", "Stores"),
		("wip_warehouse", "WIP"),
	]:
		if not s.get(field):
			wh = frappe.db.get_value(
				"Warehouse", {"name": ["like", f"%{pattern}%"], "is_group": 0}, "name"
			)
			if wh:
				s.set(field, wh)
				changed = True
	if changed:
		s.flags.ignore_permissions = True
		s.save(ignore_permissions=True)


def ensure_ops_role():
	if not frappe.db.exists("Role", OPS_ROLE):
		frappe.get_doc(
			{"doctype": "Role", "role_name": OPS_ROLE, "desk_access": 1}
		).insert(ignore_permissions=True)


def seed_departments():
	if not frappe.db.exists("DocType", "Lumirise Department Map"):
		return
	for dept, hod_name, sup_name, desc in DEPARTMENTS:
		if frappe.db.exists("Lumirise Department Map", dept):
			continue
		frappe.get_doc(
			{
				"doctype": "Lumirise Department Map",
				"department": dept,
				"hod_name": hod_name,
				"supervisor_name": sup_name,
				"description": desc,
				"escalation_hours": 24,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)


def seed_kanban_board():
	if not frappe.db.exists("DocType", "Lumirise Task"):
		return
	if frappe.db.exists("Kanban Board", KANBAN_BOARD):
		return
	board = frappe.get_doc(
		{
			"doctype": "Kanban Board",
			"kanban_board_name": KANBAN_BOARD,
			"reference_doctype": "Lumirise Task",
			"field_name": "status",
			"private": 0,
			"show_labels": 1,
			"columns": [
				{"column_name": name, "status": "Active", "indicator": colour}
				for name, colour in KANBAN_COLUMNS
			],
		}
	)
	board.flags.ignore_permissions = True
	board.insert(ignore_permissions=True)
