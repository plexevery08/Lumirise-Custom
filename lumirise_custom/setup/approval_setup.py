"""Idempotent seed for the Lumirise approval chains (Ajay review, 2026-06-14).

Implements two requirements Ajay raised on the 2026-06-14 review call:

  * INDENT is a *planning* artifact, so it is approved by the **Planning Manager**
    in a single step -- NOT the Purchase Manager (who used to sit in the chain).
    Ref transcript 00:19:22-00:20:42.
  * The PURCHASE ORDER is the *commercial release*, so it carries its own
    **Purchase Head** release approval. Ref 00:20:25 "for purchase head, purchase
    order releasing, approval should be needed."

Everything here is safe to run repeatedly -- roles/states/actions are created only
if missing, and the two Workflows are upserted (child tables fully rebuilt) so the
desired shape is reasserted on every migrate. Roles are also ensured in
before_migrate so the Workflow `allowed` links resolve during schema sync.

Run standalone:  bench --site site.com execute \
    lumirise_custom.setup.approval_setup.setup_approvals
"""

import frappe

# Roles the approval chains reference. Standard "Purchase Manager" already ships.
# "Planning User" = the maker who drafts a Material Planning (Planning Manager checks).
APPROVAL_ROLES = ["Planning User", "Planning Manager", "Purchase Head", "MD", "Factory Store Manager", "Line Supervisor"]

WORKFLOW_STATES = [
	# (name, style, icon)
	("Pending Planning Manager", "Warning", ""),
	("Pending Purchase Head", "Warning", ""),
	("Released", "Success", "ok-sign"),
	("Pending MD", "Warning", ""),
	("Approved", "Success", "ok-sign"),
	("Rejected", "Danger", "remove"),
	("Ordered", "Primary", ""),
]

WORKFLOW_ACTIONS = [
	"Submit for Approval",
	"Planning Manager Approve",
	"Submit for Release",
	"Purchase Head Approve",
	"Submit for MD Approval",
	"MD Approve",
	"Reject",
]


def ensure_approval_roles():
	"""Create the approval roles if missing. Called from before_migrate too so the
	Workflow `allowed` role links exist when the workflows are (re)imported."""
	for role in APPROVAL_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc(
				{"doctype": "Role", "role_name": role, "desk_access": 1}
			).insert(ignore_permissions=True)


def _ensure_states():
	for name, style, icon in WORKFLOW_STATES:
		if not frappe.db.exists("Workflow State", name):
			frappe.get_doc(
				{
					"doctype": "Workflow State",
					"workflow_state_name": name,
					"style": style,
					"icon": icon,
				}
			).insert(ignore_permissions=True)


def _ensure_actions():
	for action in WORKFLOW_ACTIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(
				{"doctype": "Workflow Action Master", "workflow_action_name": action}
			).insert(ignore_permissions=True)


def _upsert_workflow(name, document_type, states, transitions):
	"""Create or rebuild a Workflow so its desired states/transitions are reasserted.
	Child tables are fully replaced each run (idempotent)."""
	if frappe.db.exists("Workflow", name):
		wf = frappe.get_doc("Workflow", name)
	else:
		wf = frappe.new_doc("Workflow")
		wf.workflow_name = name
	wf.document_type = document_type
	wf.is_active = 1
	wf.workflow_state_field = "workflow_state"
	wf.send_email_alert = 0
	wf.override_status = 0
	wf.set("states", [])
	for s in states:
		wf.append(
			"states",
			{
				"state": s["state"],
				"doc_status": s["doc_status"],
				"allow_edit": s.get("allow_edit", "System Manager"),
				"send_email": 0,
			},
		)
	wf.set("transitions", [])
	for t in transitions:
		wf.append(
			"transitions",
			{
				"state": t["state"],
				"action": t["action"],
				"next_state": t["next_state"],
				"allowed": t["allowed"],
				"allow_self_approval": 1,
			},
		)
	wf.save(ignore_permissions=True)


def _indent_workflow():
	"""Indent Approval -> single Planning Manager approval (no Purchase Manager).

	Draft -> Pending Planning Manager -> Approved (submit) | Rejected.
	'Ordered' is set outside the workflow by the PO on_submit hook
	(indent.mark_indents_ordered), so it is intentionally NOT a transition here.
	"""
	states = [
		{"state": "Draft", "doc_status": "0"},
		{"state": "Pending Planning Manager", "doc_status": "0"},
		{"state": "Approved", "doc_status": "1"},
		{"state": "Rejected", "doc_status": "0"},
	]
	transitions = [
		{
			"state": "Draft",
			"action": "Submit for Approval",
			"next_state": "Pending Planning Manager",
			"allowed": "Planning Manager",
		},
		{
			"state": "Pending Planning Manager",
			"action": "Planning Manager Approve",
			"next_state": "Approved",
			"allowed": "Planning Manager",
		},
		{
			"state": "Pending Planning Manager",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "Planning Manager",
		},
	]
	_upsert_workflow("Indent Approval", "Indent", states, transitions)


def _purchase_order_workflow():
	"""Purchase Order Release -> THREE authorizations before the PO is released to
	the supplier (Rishitha, 2026-07-20 call ~01:15:26 "three authorizations: we'll
	release the PO, next Purchase Head will authorize, next MD sir will authorize —
	it's mandatory before we release to suppliers").

	Draft -> Pending Purchase Head -> Pending MD -> Released (submit) | Rejected.
	  1. Purchase (Purchase Manager) raises + "Submit for Release".
	  2. Purchase Head authorizes.
	  3. MD gives the final authorization, which submits the PO (doc_status 1).

	The PO on_submit hooks (mark_indents_ordered, status_sync) still fire when the
	workflow submits the document at the 'Released' (doc_status 1) state — that only
	happens now on MD approval, so the indents are not marked Ordered until the PO
	is fully authorized.
	"""
	states = [
		{"state": "Draft", "doc_status": "0"},
		{"state": "Pending Purchase Head", "doc_status": "0"},
		{"state": "Pending MD", "doc_status": "0"},
		{"state": "Released", "doc_status": "1"},
		{"state": "Rejected", "doc_status": "0"},
	]
	transitions = [
		{
			"state": "Draft",
			"action": "Submit for Release",
			"next_state": "Pending Purchase Head",
			"allowed": "Purchase Manager",
		},
		{
			"state": "Pending Purchase Head",
			"action": "Purchase Head Approve",
			"next_state": "Pending MD",
			"allowed": "Purchase Head",
		},
		{
			"state": "Pending Purchase Head",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "Purchase Head",
		},
		{
			"state": "Pending MD",
			"action": "MD Approve",
			"next_state": "Released",
			"allowed": "MD",
		},
		{
			"state": "Pending MD",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "MD",
		},
	]
	_upsert_workflow("Purchase Order Release", "Purchase Order", states, transitions)


def _rm_price_book_workflow():
	"""RM Price Book -> MD approval. Draft -> Pending MD -> Approved (submit) |
	Rejected. Purchase fills/uploads the book; MD approves; on_submit pushes the
	rates into costing. Ref 01:00:57 "it should be approved by MD."
	"""
	states = [
		{"state": "Draft", "doc_status": "0"},
		{"state": "Pending MD", "doc_status": "0"},
		{"state": "Approved", "doc_status": "1"},
		{"state": "Rejected", "doc_status": "0"},
	]
	transitions = [
		{
			"state": "Draft",
			"action": "Submit for MD Approval",
			"next_state": "Pending MD",
			"allowed": "Purchase Manager",
		},
		{
			"state": "Pending MD",
			"action": "MD Approve",
			"next_state": "Approved",
			"allowed": "MD",
		},
		{
			"state": "Pending MD",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "MD",
		},
	]
	_upsert_workflow("RM Price Book Approval", "RM Price Book", states, transitions)


def _material_planning_workflow():
	"""Material Planning Approval -> maker/checker (added 2026-07-06).

	The planner (**Planning User**) drafts the plan and "Submit for Approval"; the
	**Planning Manager** approves, which SUBMITS the document (doc_status 1) and so
	fires MaterialPlanning.on_submit -> creates the Work Order(s) + the consolidated
	Indent. In other words, approval == "Post".

	Draft -> Pending Planning Manager -> Approved (submit) | Rejected.

	The child Indent keeps its OWN separate Planning Manager approval (kept
	deliberately per the 2026-07-06 decision -- Planning Manager approves twice).
	"""
	states = [
		{"state": "Draft", "doc_status": "0", "allow_edit": "Planning User"},
		{"state": "Pending Planning Manager", "doc_status": "0", "allow_edit": "Planning Manager"},
		{"state": "Approved", "doc_status": "1", "allow_edit": "Planning Manager"},
		{"state": "Rejected", "doc_status": "0", "allow_edit": "Planning User"},
	]
	transitions = [
		{
			"state": "Draft",
			"action": "Submit for Approval",
			"next_state": "Pending Planning Manager",
			"allowed": "Planning User",
		},
		{
			"state": "Pending Planning Manager",
			"action": "Planning Manager Approve",
			"next_state": "Approved",
			"allowed": "Planning Manager",
		},
		{
			"state": "Pending Planning Manager",
			"action": "Reject",
			"next_state": "Rejected",
			"allowed": "Planning Manager",
		},
	]
	_upsert_workflow("Material Planning Approval", "Material Planning", states, transitions)


def setup_approvals():
	"""Entry point -- ensure roles, states, actions, then upsert the workflows."""
	ensure_approval_roles()
	_ensure_states()
	_ensure_actions()
	_indent_workflow()
	_purchase_order_workflow()
	_rm_price_book_workflow()
	_material_planning_workflow()
	frappe.db.commit()
