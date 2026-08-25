"""Permission-aware Lumirise Desk workspaces.

The workspace layer is navigation only. DocPerms, User Permissions, permission
queries and Workflow transitions remain the access-control boundary.

Workspace definitions live here instead of being hand-edited in the Desk so a
migrate can reproduce the department navigation on local, staging and Cloud.
Targets that are not installed on a particular bench are skipped; this keeps
migrate safe while still allowing the same manifest to span the full roadmap.
"""

from __future__ import annotations

import frappe


WORKSPACE_MODULE = "Lumirise Custom"
DESK_TITLE = "Lumirise Desk"

LEGACY_WORKSPACE_NAMES = {
	"Lumirise": "Lumirise Desk",
	"Management": "Management Cockpit",
}

LEGACY_HIDDEN_WORKSPACES = ("Lumirise Planning",)


def _d(label: str, target: str, color: str = "Blue") -> dict:
	return {"label": label, "link_to": target, "type": "DocType", "color": color, "doc_view": "List"}


def _r(label: str, target: str, reference: str, color: str = "Grey") -> dict:
	return {
		"label": label,
		"link_to": target,
		"type": "Report",
		"report_ref_doctype": reference,
		"color": color,
		"doc_view": "",
	}


def _break(label: str) -> dict:
	return {"label": label, "type": "Card Break", "hidden": 0}


def _chart(label: str, target: str, color: str = "Blue") -> dict:
	return {"label": label, "chart_name": target, "type": "Chart", "color": color}


def _card(label: str, target: str, color: str = "Blue") -> dict:
	return {"label": label, "number_card_name": target, "type": "Number Card", "color": color}


COMMON_DASHBOARD = (
	_card("Sales Orders", "Sales Orders Count", "Blue"),
	_card("Purchase Orders", "Purchase Orders Count", "Orange"),
	_card("Open Work Orders", "Open Work Orders", "Green"),
	_card("Active Items", "Total Active Items", "Purple"),
	_chart("Sales Order Trends", "Sales Order Trends", "Blue"),
	_chart("Stock Value by Item Group", "Stock Value by Item Group", "Orange"),
	_chart("Work Order Analysis", "Work Order Analysis", "Green"),
)


DEPARTMENT_DASHBOARDS = {
	"Sales & Order Desk": (
		_card("Sales Orders", "Sales Orders Count", "Blue"),
		_card("Orders to Deliver", "Sales Orders to Deliver", "Green"),
		_card("Total Sales Amount", "Total Sales Amount", "Purple"),
		_chart("Sales Order Trends", "Sales Order Trends", "Blue"),
		_chart("Sales Order Analysis", "Sales Order Analysis", "Green"),
		_chart("Top Customers", "Top Customers", "Orange"),
	),
	"ERP Admin & Control Tower": (
		_card("System Users", "Users", "Blue"),
		_card("Error Logs", "Error Logs", "Red"),
		_card("Scheduled Jobs", "Scheduled Jobs", "Orange"),
		_chart("Background Job Activity", "Background Job Activity", "Purple"),
		_chart("Login Activity", "Login Activity", "Green"),
	),
	"Planning - PPC": (
		_card("Orders to Deliver", "Sales Orders to Deliver", "Blue"),
		_card("Open Work Orders", "Open Work Orders", "Green"),
		_card("POs to Receive", "Purchase Orders to Receive", "Orange"),
		_chart("Material Request Analysis", "Material Request Analysis", "Purple"),
		_chart("Pending Work Order", "Pending Work Order", "Red"),
		_chart("Work Order Quantity", "Work Order Qty Analysis", "Blue"),
	),
	"BOM Engineering & Costing": (
		_card("Active Items", "Total Active Items", "Blue"),
		_card("Manufactured Items", "Manufactured Items Value", "Green"),
		_chart("Item-wise Annual Sales", "Item-wise Annual Sales", "Purple"),
		_chart("Sales Order Analysis", "Sales Order Analysis", "Orange"),
	),
	"Purchase - Procurement": (
		_card("Purchase Orders", "Purchase Orders Count", "Blue"),
		_card("POs to Receive", "Purchase Orders to Receive", "Green"),
		_card("POs to Bill", "Purchase Orders to Bill", "Orange"),
		_chart("Purchase Order Trends", "Purchase Order Trends", "Blue"),
		_chart("Purchase Order Analysis", "Purchase Order Analysis", "Purple"),
		_chart("Top Suppliers", "Top Suppliers", "Green"),
	),
	"Subcontracting": (
		_card("Outward Orders", "Subcontracting Outward Order Count", "Blue"),
		_card("Inward Orders", "Subcontracting Inward Order Count", "Green"),
		_chart("Subcontracting Orders", "Subcontracting Order", "Orange"),
		_chart("Purchase Receipt Trends", "Purchase Receipt Trends", "Purple"),
	),
	"RM Stores - Warehouse": (
		_card("Warehouses", "Total Warehouses", "Blue"),
		_card("Stock Value", "Total Stock Value", "Green"),
		_card("Active Items", "Total Active Items", "Purple"),
		_chart("Stock Value by Item Group", "Stock Value by Item Group", "Blue"),
		_chart("Warehouse-wise Stock Value", "Warehouse wise Stock Value", "Orange"),
		_chart("Item Shortage Summary", "Item Shortage Summary", "Red"),
	),
	"Production - Shop Floor": (
		_card("Open Work Orders", "Open Work Orders", "Blue"),
		_card("WIP Work Orders", "WIP Work Orders", "Orange"),
		_card("Completed This Month", "Monthly Completed Work Order", "Green"),
		_chart("Work Order Analysis", "Work Order Analysis", "Blue"),
		_chart("Pending Work Order", "Pending Work Order", "Red"),
		_chart("Produced Quantity", "Produced Quantity", "Purple"),
	),
	"Quality": (
		_card("Monthly Inspections", "Monthly Quality Inspection", "Blue"),
		_card("Health Red Runs", "Health: Red Runs", "Red"),
		_chart("Quality Inspection Analysis", "Quality Inspection Analysis", "Green"),
		_chart("Quality Inspections", "Quality Inspections", "Purple"),
	),
	"FG Store & Dispatch": (
		_card("Orders to Deliver", "Sales Orders to Deliver", "Blue"),
		_card("Active Items", "Total Active Items", "Green"),
		_chart("Delivery Trends", "Delivery Trends", "Purple"),
		_chart("Sales Order Trends", "Sales Order Trends", "Orange"),
	),
	"Logistics & Security": (
		_card("Orders to Deliver", "Sales Orders to Deliver", "Blue"),
		_card("POs to Receive", "Purchase Orders to Receive", "Orange"),
		_chart("Delivery Trends", "Delivery Trends", "Green"),
		_chart("Purchase Receipt Trends", "Purchase Receipt Trends", "Purple"),
	),
	"Accounts & Finance": (
		_card("Incoming Bills", "Total Incoming Bills", "Orange"),
		_card("Outgoing Bills", "Total Outgoing Bills", "Blue"),
		_card("Incoming Payments", "Total Incoming Payment", "Green"),
		_chart("Profit and Loss", "Profit and Loss", "Purple"),
		_chart("Accounts Receivable", "Accounts Receivable Ageing", "Blue"),
		_chart("Accounts Payable", "Accounts Payable Ageing", "Orange"),
	),
	"Management Cockpit": (
		_card("Sales Orders", "Sales Orders Count", "Blue"),
		_card("Purchase Orders", "Purchase Orders Count", "Orange"),
		_card("Open Work Orders", "Open Work Orders", "Green"),
		_chart("Profit and Loss", "Profit and Loss", "Purple"),
		_chart("Sales Order Trends", "Sales Order Trends", "Blue"),
		_chart("Stock Value by Item Group", "Stock Value by Item Group", "Orange"),
	),
}


def _spec(
	name: str,
	label: str,
	icon: str,
	sequence: int,
	roles: tuple[str, ...],
	sections: tuple[tuple[str, tuple[dict, ...]], ...],
	dashboard: tuple[dict, ...] = (),
	) -> dict:
	if not dashboard:
		dashboard = COMMON_DASHBOARD if name == DESK_TITLE else DEPARTMENT_DASHBOARDS.get(name, ())
	shortcuts = []
	charts = []
	number_cards = []
	content = []
	for section_index, (section, entries) in enumerate(sections):
		content.append(
			{
				"id": f"lr-{name.lower().replace(' ', '-')}-{section_index}-header",
				"type": "header",
				"data": {"text": section, "level": 4, "col": 12},
			}
		)
		for entry_index, entry in enumerate(entries):
			if entry["type"] == "Card Break":
				continue
			if entry["type"] == "DocType" and not frappe.db.exists("DocType", entry["link_to"]):
				continue
			if entry["type"] == "Report" and not frappe.db.exists("Report", entry["link_to"]):
				continue
			shortcuts.append(entry)
			content.append(
				{
					"id": f"lr-{name.lower().replace(' ', '-')}-{section_index}-{entry_index}",
					"type": "shortcut",
					"data": {"shortcut_name": entry["label"], "col": 3},
				}
			)
	for entry_index, entry in enumerate(dashboard):
		if entry["type"] == "Chart":
			if not frappe.db.exists("Dashboard Chart", entry["chart_name"]):
				continue
			charts.append({"chart_name": entry["chart_name"], "label": entry["label"]})
			content.insert(
				entry_index,
				{
					"id": f"lr-{name.lower().replace(' ', '-')}-dashboard-{entry_index}",
					"type": "chart",
					"data": {"chart_name": entry["chart_name"], "col": 12},
				},
			)
		elif entry["type"] == "Number Card":
			if not frappe.db.exists("Number Card", entry["number_card_name"]):
				continue
			number_cards.append({"label": entry["label"], "number_card_name": entry["number_card_name"]})
			content.insert(
				entry_index,
				{
					"id": f"lr-{name.lower().replace(' ', '-')}-card-{entry_index}",
					"type": "number_card",
					"data": {"number_card_name": entry["number_card_name"], "col": 3},
				},
			)
	return {
		"name": name,
		"label": label,
		"title": label,
		"icon": icon,
		"sequence_id": sequence,
		"roles": roles,
		"sections": sections,
		"shortcuts": shortcuts,
		"content": frappe.as_json(content),
		"charts": charts,
		"number_cards": number_cards,
	}


COMMON = (
	("My Work & Approvals", (
		_d("Lumirise Tasks", "Lumirise Task", "Blue"),
		_d("Health Check Runs", "Health Check Run", "Red"),
		_r("Open Health Failures", "Open Health Failures", "Health Check Run", "Red"),
		_r("Health Check Trend", "Health Check Trend", "Health Check Run"),
	)),
	("Cross-functional Flow", (
		_d("Sales Orders", "Sales Order", "Blue"),
		_d("Material Planning", "Material Planning", "Green"),
		_d("Purchase Orders", "Purchase Order", "Orange"),
		_d("Work Orders", "Work Order", "Green"),
		_d("Delivery Notes", "Delivery Note", "Blue"),
	)),
	("Operations & Settings", (
		_d("Lumirise Operations Settings", "Lumirise Operations Settings", "Purple"),
		_d("Sales Platform Settings", "Sales Platform Settings", "Blue"),
		_d("System Settings", "System Settings", "Grey"),
		_d("Company", "Company", "Blue"),
		_d("Global Defaults", "Global Defaults", "Green"),
		_d("Buying Settings", "Buying Settings", "Orange"),
		_d("Selling Settings", "Selling Settings", "Blue"),
		_d("Stock Settings", "Stock Settings", "Cyan"),
		_d("Manufacturing Settings", "Manufacturing Settings", "Purple"),
		_d("Accounts Settings", "Accounts Settings", "Red"),
	)),
	("Common Masters & Governance", (
		_d("Users", "User", "Blue"),
		_d("Roles", "Role", "Purple"),
		_d("User Permissions", "User Permission", "Orange"),
		_d("Workflows", "Workflow", "Green"),
		_d("Workflow States", "Workflow State", "Blue"),
		_d("Workflow Actions", "Workflow Action Master", "Orange"),
		_d("Notifications", "Notification", "Cyan"),
		_d("Assignment Rules", "Assignment Rule", "Purple"),
		_d("Print Formats", "Print Format", "Grey"),
		_d("Document Naming Rules", "Document Naming Rule", "Blue"),
	)),
	("Common Reports & Logs", (
		_d("Activity Log", "Activity Log", "Grey"),
		_d("Error Log", "Error Log", "Red"),
		_d("Notification Log", "Notification Log", "Orange"),
		_d("Email Queue", "Email Queue", "Blue"),
		_d("File Manager", "File", "Green"),
		_d("ToDo", "ToDo", "Purple"),
		_r("Document Audit Trail", "Document Audit Trail", "Version", "Grey"),
		_r("System Usage", "System Usage", "Activity Log", "Blue"),
	)),
)


WORKSPACES = (
	_spec("Lumirise Desk", "Lumirise Desk", "sell", 1, (), COMMON),
	_spec(
		"Sales & Order Desk",
		"Sales & Order Desk",
		"sell",
		10,
		("Sales User", "Sales Manager", "Sales Approver", "Sales Auditor", "System Manager"),
		(
			("Today / Create", (_d("Customers", "Customer"), _d("Quotations", "Quotation", "Green"), _d("Sales Orders", "Sales Order", "Blue"), _d("Sales Forecast", "Sales Forecast", "Orange"))),
			("Order Flow", (_d("Material Planning", "Material Planning", "Green"), _d("Delivery Notes", "Delivery Note", "Blue"), _d("Customer PDI", "Customer PDI", "Purple"), _d("Sales Returns", "Sales Invoice", "Red"))),
			("Reports / Control", (_r("Sales Order Line Progress", "Sales Order Line Progress", "Sales Order", "Blue"), _r("Customer Quote Summary", "Customer Quote Summary", "Quotation"), _r("Listing of Documents", "Listing of Documents", "Sales Order"))),
			("Exceptions", (_d("Lumirise Tasks", "Lumirise Task", "Orange"), _d("Customer Complaints", "Issue", "Red"))),
		),
	),
	_spec(
		"ERP Admin & Control Tower",
		"ERP Admin & Control Tower",
		"dashboard",
		11,
		("System Manager", "Lumirise Operations", "MD", "Workspace Manager"),
		(
			("Control Tower", (_d("Lumirise Tasks", "Lumirise Task", "Blue"), _d("Health Check Runs", "Health Check Run", "Red"), _r("Open Health Failures", "Open Health Failures", "Health Check Run", "Red"), _r("Health Check Trend", "Health Check Trend", "Health Check Run"))),
			("Masters & Governance", (_d("Users", "User"), _d("Roles", "Role", "Purple"), _d("User Permissions", "User Permission", "Orange"), _d("Items", "Item", "Green"))),
			("Workflow Monitoring", (_r("Listing of Documents", "Listing of Documents", "Sales Order"), _r("Line Status", "Line Status", "Work Order", "Blue"))),
		),
	),
	_spec(
		"Planning - PPC",
		"Planning - PPC",
		"calendar",
		12,
		("Planning User", "Planning Manager", "Manufacturing Manager", "System Manager"),
		(
			("Plan & Reserve", (_d("Material Planning", "Material Planning", "Green"), _d("Material Resource Planning", "Material Resource Planning", "Blue"), _d("Production Lines", "Production Line", "Orange"), _d("Sales Orders", "Sales Order"))),
			("Procurement Handoff", (_d("Indent Plans", "Indent Plan", "Orange"), _d("Indents", "Indent", "Orange"), _d("Material Requisitions", "Material Requisition", "Blue"))),
			("Reports / Control", (_r("Production Plan", "Lumirise Production Plan", "Sales Order", "Green"), _r("RM Stock & Reservations", "RM Stock and Reservation Tracker", "Item", "Orange"), _r("Material Accountability", "Material Accountability", "Work Order", "Red"), _r("Daily Line Summary", "Daily Line Summary", "Work Order", "Blue"))),
		),
	),
	_spec(
		"BOM Engineering & Costing",
		"BOM Engineering & Costing",
		"organization",
		13,
		("Item Manager", "Pricing Manager", "Sales Master Manager", "Manufacturing Manager", "System Manager"),
		(
			("Masters", (_d("Items", "Item", "Blue"), _d("BOMs", "BOM", "Green"), _d("Workstations", "Workstation", "Orange"), _d("Operations", "Operation", "Orange"))),
			("Costing & Approval", (_d("Price Lists", "Price List", "Blue"), _d("Currency Exchange", "Currency Exchange", "Green"), _d("BOM Change Requests", "BOM Change Request", "Purple"))),
			("Reports / Control", (_r("Costing Rate Breach", "Costing Rate Breach", "BOM", "Red"), _r("Rate Variance Monitor", "Rate Variance Monitor", "BOM", "Orange"))),
		),
	),
	_spec(
		"Purchase - Procurement",
		"Purchase - Procurement",
		"buying",
		14,
		("Purchase User", "Purchase Manager", "Purchase Head", "Planning Manager", "System Manager"),
		(
			("Purchase Queue", (_d("Suppliers", "Supplier", "Blue"), _d("Material Requisitions", "Material Requisition", "Orange"), _d("Indents", "Indent", "Orange"), _d("Purchase Plans", "Purchase Plan", "Green"), _d("Purchase Orders", "Purchase Order", "Blue"))),
			("Receipt & Vendor Control", (_d("Vendor PDI", "Vendor PDI", "Purple"), _d("Inbound Logistics", "Inbound Logistics", "Cyan"), _d("Purchase Receipts", "Purchase Receipt", "Green"), _d("Purchase Invoices", "Purchase Invoice", "Orange"))),
			("Reports / Exceptions", (_r("PO Stage Status", "PO Stage Status", "Purchase Order", "Orange"), _r("Supplier Price Comparison", "Supplier Price Comparison", "Supplier Quotation", "Blue"), _r("Supplier Aging", "Accounts Payable", "Supplier", "Red"))),
		),
	),
	_spec(
		"Subcontracting",
		"Subcontracting",
		"share",
		15,
		("Purchase User", "Purchase Manager", "Purchase Head", "Planning User", "Factory Store Manager", "System Manager"),
		(
			("Job-work Flow", (_d("Subcontracting Orders", "Subcontracting Order", "Blue"), _d("Subcontracting Receipts", "Subcontracting Receipt", "Green"), _d("Purchase Orders", "Purchase Order", "Orange"))),
			("Materials & Logistics", (_d("Stock Entries", "Stock Entry", "Orange"), _d("Inbound Logistics", "Inbound Logistics", "Cyan"), _d("Suppliers", "Supplier", "Blue"))),
			("Exceptions", (_d("Purchase Receipts", "Purchase Receipt", "Green"), _d("Purchase Invoices", "Purchase Invoice", "Orange"), _d("Lumirise Tasks", "Lumirise Task", "Red"))),
		),
	),
	_spec(
		"RM Stores - Warehouse",
		"RM Stores - Warehouse",
		"stock",
		16,
		("Factory Store Manager", "Stock Manager", "Stock User", "System Manager"),
		(
			("Inward & Put-away", (_d("Material Receipts", "Material Receipt", "Green"), _d("Purchase Receipts", "Purchase Receipt", "Blue"), _d("Warehouses", "Warehouse", "Orange"), _d("RM Packages", "RM Package", "Cyan"))),
			("Issue & Transfer", (_d("Material Requisitions", "Material Requisition", "Blue"), _d("Material Issues", "Material Issue", "Orange"), _d("Stock Entries", "Stock Entry", "Green"), _d("Batches", "Batch", "Purple"))),
			("Reports / Exceptions", (_r("RM Stock & Reservations", "RM Stock and Reservation Tracker", "Item", "Orange"), _r("Material Issue Register", "Material Issue Register", "Material Issue", "Blue"), _r("RM Rejection Ageing", "RM Rejection Ageing", "Item", "Red"), _r("Stock Balance", "Stock Balance", "Item", "Grey"))),
		),
	),
	_spec(
		"Production - Shop Floor",
		"Production - Shop Floor",
		"manufacturing",
		17,
		("Manufacturing User", "Manufacturing Manager", "Line Manager", "System Manager"),
		(
			("Material to Line", (_d("Material Requisitions", "Material Requisition", "Blue"), _d("Material Issues", "Material Issue", "Orange"), _d("Line Material Allocations", "Line Material Allocation", "Green"), _d("Work Orders", "Work Order", "Blue"))),
			("Execute & Close", (_d("Job Cards", "Job Card", "Green"), _d("Line Daily Closings", "Line Daily Closing", "Orange"), _d("Production Lines", "Production Line", "Purple"), _d("Stock Entries", "Stock Entry", "Cyan"))),
			("Reports / Exceptions", (_r("Line Status", "Line Status", "Work Order", "Blue"), _r("Daily Line Summary", "Daily Line Summary", "Work Order", "Green"), _r("Daily Production Output", "Daily Production Output Cross Check", "Work Order", "Orange"), _r("Material Issue Register", "Material Issue Register", "Material Issue", "Red"))),
		),
	),
	_spec(
		"Quality",
		"Quality",
		"quality",
		18,
		("Quality Manager", "Manufacturing Manager", "Factory Store Manager", "System Manager"),
		(
			("Inspection Checkpoints", (_d("Vendor PDI", "Vendor PDI", "Purple"), _d("IQC", "IQC", "Yellow"), _d("Quality Inspections", "Quality Inspection", "Blue"), _d("Customer PDI", "Customer PDI", "Green"))),
			("Parameters & Evidence", (_d("Defect Codes", "Lumirise Defect Code", "Red"), _d("IQC Samples", "IQC Sample", "Cyan"), _d("Quality Inspection Templates", "Quality Inspection Template", "Orange"), _d("Non-Conformances", "Non Conformance", "Red"))),
			("Reports / Exceptions", (_r("Batch-wise Rejection", "Batch Wise Rejection", "IQC", "Red"), _r("RM Rejection Ageing", "RM Rejection Ageing", "Item", "Orange"), _r("Material Receipt Stock Analysis", "Material Receipt Stock Analysis", "Purchase Receipt", "Blue"))),
		),
	),
	_spec(
		"FG Store & Dispatch",
		"FG Store & Dispatch",
		"truck",
		19,
		("Factory Store Manager", "Delivery Manager", "Delivery User", "Fulfillment User", "Sales User", "System Manager"),
		(
			("FG & Packing", (_d("Items", "Item", "Blue"), _d("Batches", "Batch", "Purple"), _d("Stock Entries", "Stock Entry", "Orange"), _d("Packing Slips", "Packing Slip", "Green"))),
			("Dispatch Flow", (_d("Customer PDI", "Customer PDI", "Yellow"), _d("Delivery Notes", "Delivery Note", "Blue"), _d("Shipments", "Shipment", "Cyan"), _d("Sales Returns", "Sales Invoice", "Red"))),
			("Reports / Control", (_r("Sales Order Line Progress", "Sales Order Line Progress", "Sales Order", "Blue"), _r("Listing of Documents", "Listing of Documents", "Sales Order", "Grey"))),
		),
	),
	_spec(
		"Logistics & Security",
		"Logistics & Security",
		"truck",
		20,
		("Delivery Manager", "Delivery User", "Fulfillment User", "Factory Store Manager", "System Manager"),
		(
			("Inbound Logistics", (_d("Inbound Logistics", "Inbound Logistics", "Cyan"), _d("Purchase Receipts", "Purchase Receipt", "Green"), _d("Suppliers", "Supplier", "Blue"))),
			("Outbound & Gate", (_d("Shipments", "Shipment", "Blue"), _d("Delivery Notes", "Delivery Note", "Green"), _d("Vehicles", "Vehicle", "Orange"), _d("Sales Orders", "Sales Order", "Purple"))),
			("Reports / Exceptions", (_r("PO Stage Status", "PO Stage Status", "Purchase Order", "Orange"), _r("Listing of Documents", "Listing of Documents", "Delivery Note", "Grey"))),
		),
	),
	_spec(
		"Accounts & Finance",
		"Accounts & Finance",
		"accounting",
		21,
		("Accounts User", "Accounts Manager", "MD", "System Manager"),
		(
			("Receivable / Payable", (_d("Sales Invoices", "Sales Invoice", "Blue"), _d("Purchase Invoices", "Purchase Invoice", "Orange"), _d("Payment Entries", "Payment Entry", "Green"), _d("Journal Entries", "Journal Entry", "Purple"))),
			("Tax, Cash & Assets", (_d("Chart of Accounts", "Account", "Blue"), _d("Bank Accounts", "Bank Account", "Cyan"), _d("Assets", "Asset", "Orange"), _d("Accounting Periods", "Accounting Period", "Red"))),
			("Reports / Close", (_r("Daily Cash Flow", "Daily Cash Flow", "Payment Entry", "Green"), _r("Accounts Receivable", "Accounts Receivable", "Sales Invoice", "Blue"), _r("Accounts Payable", "Accounts Payable", "Purchase Invoice", "Orange"), _r("Profit and Loss", "Profit and Loss Statement", "GL Entry", "Purple"), _r("Stock Valuation", "Stock Balance", "Item", "Grey"))),
		),
	),
	_spec(
		"Management Cockpit",
		"Management Cockpit",
		"organization",
		22,
		("MD", "Lumirise Operations", "System Manager"),
		(
			("Executive Review", (_r("Profit and Loss", "Profit and Loss Statement", "GL Entry", "Blue"), _r("Cash Flow", "Daily Cash Flow", "Payment Entry", "Green"), _r("Stock Valuation", "Stock Balance", "Item", "Orange"))),
			("Operations Review", (_r("Production Plan", "Lumirise Production Plan", "Sales Order", "Green"), _r("PO Stage Status", "PO Stage Status", "Purchase Order", "Orange"), _r("Batch-wise Rejection", "Batch Wise Rejection", "IQC", "Red"), _r("Line Status", "Line Status", "Work Order", "Blue"))),
			("Approvals & Exceptions", (_d("Lumirise Tasks", "Lumirise Task", "Red"), _r("Open Health Failures", "Open Health Failures", "Health Check Run", "Red"))),
		),
	),
)


def _ensure_roles() -> None:
	roles = {role for spec in WORKSPACES for role in spec["roles"] if role}
	for role in sorted(roles):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def _upsert(spec: dict) -> None:
	values = {
		"doctype": "Workspace",
		"name": spec["name"],
		"label": spec["label"],
		"title": spec["title"],
		"module": WORKSPACE_MODULE,
		"app": "lumirise_custom",
		"type": "Workspace",
		"icon": spec["icon"],
		"public": 1,
		"is_hidden": 0,
		"hide_custom": 1,
		"sequence_id": spec["sequence_id"],
		"roles": [{"role": role} for role in spec["roles"]],
		"shortcuts": spec["shortcuts"],
		"content": spec["content"],
		"links": [],
		"charts": spec.get("charts", []),
		"number_cards": spec.get("number_cards", []),
		"quick_lists": [],
	}
	try:
		doc = frappe.get_doc("Workspace", spec["name"])
	except frappe.DoesNotExistError:
		doc = frappe.get_doc(values)
		try:
			doc.insert(ignore_permissions=True)
			return
		except frappe.DuplicateEntryError:
			# A workspace may have been imported by the fixture hook in the same
			# migrate transaction; fetch it and continue with the canonical payload.
			doc = frappe.get_doc("Workspace", spec["name"])
	for field, value in values.items():
		if field != "doctype":
			doc.set(field, value)
	doc.save(ignore_permissions=True)


def _ensure_department_sidebar() -> None:
	"""Create the shared department switcher used by the Desk sidebar.

	Sidebar links are navigation only. The target Workspace's role rules and
	the target DocType/report permissions still decide whether a user can open
	anything behind a link.
	"""
	if not frappe.db.exists("DocType", "Workspace Sidebar"):
		return
	if frappe.db.get_value("Workspace Sidebar", "Lumirise Departments", "name") and not frappe.db.get_value(
		"Workspace Sidebar", DESK_TITLE, "name"
	):
		frappe.rename_doc("Workspace Sidebar", "Lumirise Departments", DESK_TITLE, force=True)
	items = [
		{
			"type": "Link",
			"label": "Lumirise Home",
			"link_type": "Workspace",
			"link_to": WORKSPACES[0]["name"],
			"icon": "home",
		},
	]
	for spec in WORKSPACES[1:]:
		items.append(
			{
				"type": "Link",
				"label": spec["label"],
				"link_type": "Workspace",
				"link_to": spec["name"],
				"icon": spec["icon"],
			}
		)
	values = {
		"doctype": "Workspace Sidebar",
		"title": DESK_TITLE,
		"module": WORKSPACE_MODULE,
		"app": "lumirise_custom",
		"standard": 0,
		"items": items,
	}
	try:
		doc = frappe.get_doc("Workspace Sidebar", DESK_TITLE)
	except frappe.DoesNotExistError:
		doc = frappe.get_doc(values)
		try:
			doc.insert(ignore_permissions=True)
			return
		except frappe.DuplicateEntryError:
			doc = frappe.get_doc("Workspace Sidebar", DESK_TITLE)
	for field, value in values.items():
		if field != "doctype":
			doc.set(field, value)
	doc.save(ignore_permissions=True)


def _ensure_desk_icon() -> None:
	"""Expose Lumirise Desk in the first-level ERPNext launcher."""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return
	values = {
		"doctype": "Desktop Icon",
		"label": DESK_TITLE,
		"icon_type": "Link",
		"link_type": "Workspace Sidebar",
		"link_to": DESK_TITLE,
		"sidebar": DESK_TITLE,
		"parent_icon": "",
		"icon": "organization",
		"bg_color": "blue",
		"standard": 0,
		"app": "lumirise_custom",
		"hidden": 0,
		"restrict_removal": 1,
		"roles": [],
	}
	try:
		doc = frappe.get_doc("Desktop Icon", DESK_TITLE)
	except frappe.DoesNotExistError:
		doc = frappe.get_doc(values)
		try:
			doc.insert(ignore_permissions=True)
			return
		except frappe.DuplicateEntryError:
			doc = frappe.get_doc("Desktop Icon", DESK_TITLE)
	for field, value in values.items():
		if field != "doctype":
			doc.set(field, value)
	doc.save(ignore_permissions=True)


def setup_workspaces() -> None:
	"""Idempotently install the Lumirise Desk and department workspaces."""
	try:
		if not frappe.db.exists("DocType", "Workspace"):
			return
		_ensure_roles()
		for old_name, new_name in LEGACY_WORKSPACE_NAMES.items():
			if frappe.db.get_value("Workspace", old_name, "name") and not frappe.db.get_value(
				"Workspace", new_name, "name"
			):
				frappe.rename_doc("Workspace", old_name, new_name, force=True)
		for raw in WORKSPACES:
			_upsert(raw)
		for workspace_name in LEGACY_HIDDEN_WORKSPACES:
			if frappe.db.exists("Workspace", workspace_name):
				frappe.db.set_value("Workspace", workspace_name, "is_hidden", 1)
		_ensure_department_sidebar()
		_ensure_desk_icon()
		frappe.clear_cache()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Lumirise workspace setup failed")
