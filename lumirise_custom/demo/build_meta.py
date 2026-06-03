# Phase 5 metadata: Indent approval workflow, the Lumirise workspace, and the
# "Listing of Documents" script report (registered as a standard report so its
# files live in the app).
#
# Run:  bench --site site.com execute lumirise_custom.demo.build_meta.execute

import json

import frappe

MODULE = "Lumirise Custom"


def _ws_state(name, style):
	if not frappe.db.exists("Workflow State", name):
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": name,
						"style": style}).insert(ignore_permissions=True)


def _ensure_workflow():
	for nm, style in [("Pending Purchase Manager", "Warning"), ("Pending MD", "Warning"),
					  ("Approved", "Success"), ("Rejected", "Danger"), ("Ordered", "Primary")]:
		_ws_state(nm, style)
	# actions used as transition labels must exist as Workflow Action Master
	for act in ["Submit for Approval", "Purchase Manager Approve", "MD Approve", "Reject"]:
		if not frappe.db.exists("Workflow Action Master", act):
			frappe.get_doc({"doctype": "Workflow Action Master",
							"workflow_action_name": act}).insert(ignore_permissions=True)
	if frappe.db.exists("Workflow", "Indent Approval"):
		return
	frappe.get_doc({
		"doctype": "Workflow", "workflow_name": "Indent Approval",
		"document_type": "Indent", "is_active": 1, "workflow_state_field": "workflow_state",
		"states": [
			{"state": "Draft", "doc_status": "0", "allow_edit": "System Manager"},
			{"state": "Pending Purchase Manager", "doc_status": "0", "allow_edit": "System Manager"},
			{"state": "Pending MD", "doc_status": "0", "allow_edit": "System Manager"},
			{"state": "Approved", "doc_status": "1", "allow_edit": "System Manager"},
			{"state": "Rejected", "doc_status": "0", "allow_edit": "System Manager"},
		],
		"transitions": [
			{"state": "Draft", "action": "Submit for Approval",
			 "next_state": "Pending Purchase Manager", "allowed": "System Manager"},
			{"state": "Pending Purchase Manager", "action": "Purchase Manager Approve",
			 "next_state": "Pending MD", "allowed": "System Manager"},
			{"state": "Pending MD", "action": "MD Approve",
			 "next_state": "Approved", "allowed": "System Manager"},
			{"state": "Pending Purchase Manager", "action": "Reject",
			 "next_state": "Rejected", "allowed": "System Manager"},
			{"state": "Pending MD", "action": "Reject",
			 "next_state": "Rejected", "allowed": "System Manager"},
		],
	}).insert(ignore_permissions=True)
	print("  workflow created: Indent Approval")


def _ensure_report():
	if frappe.db.exists("Report", "Listing of Documents"):
		return
	frappe.get_doc({
		"doctype": "Report", "report_name": "Listing of Documents",
		"report_type": "Script Report", "ref_doctype": "Sales Order",
		"module": MODULE, "is_standard": "Yes",
	}).insert(ignore_permissions=True)
	print("  report created: Listing of Documents")


def _ensure_workspace():
	if frappe.db.exists("Workspace", "Lumirise"):
		return
	shortcuts = [
		("Material Planning", "DocType", "Material Planning", "Blue"),
		("Indent", "DocType", "Indent", "Orange"),
		("Vendor PDI", "DocType", "Vendor PDI", "Purple"),
		("Inbound Logistics", "DocType", "Inbound Logistics", "Cyan"),
		("IQC", "DocType", "IQC", "Yellow"),
		("Customer PDI", "DocType", "Customer PDI", "Green"),
		("Sales Order", "DocType", "Sales Order", "Blue"),
		("Purchase Order", "DocType", "Purchase Order", "Orange"),
		("Work Order", "DocType", "Work Order", "Green"),
		("Delivery Note", "DocType", "Delivery Note", "Blue"),
		("Listing of Documents", "Report", "Listing of Documents", "Grey"),
	]
	content = [{"id": frappe.generate_hash(length=10), "type": "header",
				"data": {"text": "Lumirise — Order to Dispatch", "level": 4, "col": 12}}]
	for label, _t, _link, _c in shortcuts:
		content.append({"id": frappe.generate_hash(length=10), "type": "shortcut",
						"data": {"shortcut_name": label, "col": 3}})
	ws = frappe.get_doc({
		"doctype": "Workspace", "label": "Lumirise", "title": "Lumirise",
		"module": MODULE, "icon": "sell", "public": 1, "type": "Workspace",
		"content": json.dumps(content),
	})
	for label, typ, link, color in shortcuts:
		ws.append("shortcuts", {"label": label, "type": typ, "link_to": link, "color": color})
	ws.insert(ignore_permissions=True)
	print("  workspace created: Lumirise")


def execute():
	_ensure_workflow()
	_ensure_report()
	_ensure_workspace()
	frappe.db.commit()
	print("Meta built.")
