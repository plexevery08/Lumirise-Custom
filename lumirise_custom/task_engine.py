# Lumirise Task Engine
# =====================
# Turns the cross-department handoffs / defects / rejections / missed-deadlines
# that used to live in Bitrix + WhatsApp into tracked ERP "Lumirise Task" cards.
#
# Each card is:
#   * assigned to an OWNER (the responsible department user), and
#   * shared with the SUPERVISOR (write) and HOD (read) for oversight, and
#   * @mentioned to supervisor + HOD so they get a desk/email notification.
#
# Owner / supervisor / HOD are resolved from the "Lumirise Department Map".
#
# CRITICAL DESIGN RULE: the engine is FAIL-SAFE. Task creation runs inside the
# triggering document's transaction (GRN, IQC, Sales Order, ...). A glitch in
# notification/assignment must NEVER roll back the real business operation, so
# every public entrypoint swallows + logs its own errors. The business flow
# always wins.

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

TERMINAL_STATUSES = ("Done", "Cancelled")


# ---------------------------------------------------------------------------
# Assignee resolution
# ---------------------------------------------------------------------------
def _enabled_user(user):
	"""Return the user id only if it is a real, enabled login; else None."""
	if not user:
		return None
	if not frappe.db.exists("User", user):
		return None
	if not frappe.db.get_value("User", user, "enabled"):
		return None
	return user


def resolve_department(department):
	"""Fetch the Department Map row (owner/supervisor/hod). Returns dict or None."""
	if not department or not frappe.db.exists("Lumirise Department Map", department):
		return None
	row = frappe.db.get_value(
		"Lumirise Department Map",
		department,
		["supervisor_user", "hod_user", "escalation_hours", "is_active"],
		as_dict=True,
	)
	return row


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------
def create_task(
	title,
	department=None,
	task_type="General",
	priority="Medium",
	owner_user=None,
	supervisor_user=None,
	hod_user=None,
	reference_doctype=None,
	reference_name=None,
	description=None,
	due_date=None,
	source_event=None,
	dedup=True,
):
	"""Create (or skip-if-duplicate) one Lumirise Task and notify the people on it.

	Returns the task name, or None if it was de-duplicated or failed safely.
	Never raises — safe to call from inside any doc_event handler.
	"""
	try:
		# De-duplicate: don't spawn a second open card for the same
		# (reference, source_event) pair.
		if dedup and reference_doctype and reference_name and source_event:
			existing = frappe.get_all(
				"Lumirise Task",
				filters={
					"reference_doctype": reference_doctype,
					"reference_name": reference_name,
					"source_event": source_event,
					"status": ["not in", TERMINAL_STATUSES],
				},
				limit=1,
			)
			if existing:
				return None

		dept = resolve_department(department)
		if dept:
			owner_user = owner_user or dept.get("supervisor_user") or dept.get("hod_user")
			supervisor_user = supervisor_user or dept.get("supervisor_user")
			hod_user = hod_user or dept.get("hod_user")

		owner_user = _enabled_user(owner_user)
		supervisor_user = _enabled_user(supervisor_user)
		hod_user = _enabled_user(hod_user)

		task = frappe.get_doc(
			{
				"doctype": "Lumirise Task",
				"title": title[:140],
				"status": "Open",
				"priority": priority,
				"task_type": task_type,
				"department": department if (department and frappe.db.exists("Lumirise Department Map", department)) else None,
				"owner_user": owner_user,
				"supervisor_user": supervisor_user,
				"hod_user": hod_user,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"description": description,
				"due_date": due_date,
				"source_event": source_event,
			}
		)
		task.flags.ignore_permissions = True
		task.insert(ignore_permissions=True)

		# Assign owner (write) + supervisor (write) + HOD (read) so each sees the
		# card on their personal Kanban / "To Do" and gets notified.
		_assign(task.name, owner_user, write=True)
		_assign(task.name, supervisor_user, write=True)
		_assign(task.name, hod_user, write=False)
		_mention(task, [u for u in (supervisor_user, hod_user) if u])

		return task.name
	except Exception:
		# Never let a task/notification problem break the business document.
		frappe.log_error(frappe.get_traceback(), "Lumirise Task Engine: create_task failed")
		return None


def _assign(task_name, user, write=False):
	"""Assign a user to the task (creates a ToDo + DocShare + notification)."""
	if not user:
		return
	try:
		from frappe.desk.form.assign_to import add as assign_add

		assign_add(
			{
				"assign_to": [user],
				"doctype": "Lumirise Task",
				"name": task_name,
				"description": frappe.db.get_value("Lumirise Task", task_name, "title"),
				"notify": 1,
			}
		)
		if write:
			# Upgrade the auto-created share to write so they can move the card.
			frappe.share.add(
				"Lumirise Task", task_name, user, write=1, flags={"ignore_share_permission": True}
			)
	except frappe.exceptions.DuplicateEntryError:
		pass
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Lumirise Task Engine: assign failed")


def _mention(task, users):
	"""Drop an @mention comment so supervisor/HOD get a tag notification."""
	if not users:
		return
	try:
		mentions = " ".join(f"@{u}" for u in users)
		task.add_comment(
			"Comment",
			text=f"{mentions} — tagged for oversight on this task.",
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Lumirise Task Engine: mention failed")


# ---------------------------------------------------------------------------
# Event handlers (wired via doc_events in hooks.py)
# ---------------------------------------------------------------------------
def on_sales_order_update(doc, method=None):
	"""SO approved -> hand the order off to Planning (replaces the verbal/Bitrix
	handoff). Fires when the workflow reaches an approved state."""
	state = (getattr(doc, "workflow_state", "") or "").lower()
	if "approv" not in state:
		return
	create_task(
		title=f"Plan order {doc.name} ({getattr(doc, 'customer', '')})",
		department="Planning - PPC",
		task_type="Handoff",
		priority="High",
		reference_doctype="Sales Order",
		reference_name=doc.name,
		description=f"Sales Order {doc.name} is approved. Run material planning / netting and post the plan.",
		due_date=getattr(doc, "delivery_date", None),
		source_event="so_approved",
	)


def on_material_planning_submit(doc, method=None):
	"""Plan posted -> Work Orders + Indent created. Hand off to Purchase (process
	the Indent) and Production (Work Orders are ready)."""
	indent = getattr(doc, "created_indent", None)
	if indent:
		create_task(
			title=f"Process Indent {indent} from plan {doc.name}",
			department="Purchase",
			task_type="Handoff",
			priority="High",
			reference_doctype="Indent",
			reference_name=indent,
			description=f"Material Planning {doc.name} generated Indent {indent}. Approve and convert to PO(s).",
			source_event="plan_indent",
		)
	create_task(
		title=f"Work Orders ready from plan {doc.name}",
		department="Production",
		task_type="Handoff",
		priority="Medium",
		reference_doctype="Material Planning",
		reference_name=doc.name,
		description=f"Plan {doc.name} created Work Orders: {getattr(doc, 'created_work_orders', '') or '—'}.",
		source_event="plan_workorders",
	)


def on_indent_update(doc, method=None):
	"""Indent fully approved -> task Purchase to raise the consolidated PO."""
	state = (getattr(doc, "workflow_state", "") or "").lower()
	if state != "approved":
		return
	create_task(
		title=f"Raise PO for approved Indent {doc.name}",
		department="Purchase",
		task_type="Handoff",
		priority="High",
		reference_doctype="Indent",
		reference_name=doc.name,
		description=f"Indent {doc.name} is approved. Create the consolidated Purchase Order.",
		source_event="indent_approved",
	)


def on_iqc_submit(doc, method=None):
	"""IQC with any rejection -> Defect task to Purchase (vendor claim / replace)
	tagged to the Quality + Purchase HOD."""
	# The old stored `result` field is gone (and its DB column defaults to
	# 'Accepted'), so derive the outcome live from the line qtys — otherwise this
	# early-return always fired and no rejection card ever reached Purchase.
	from frappe.utils import flt
	any_reject = any(flt(r.rejected_qty) > 0 for r in (doc.items or []))
	if not any_reject:
		return
	outcome = "Rejected" if doc.is_fully_rejected() else "Partial"
	po = getattr(doc, "purchase_order", "") or ""
	create_task(
		title=f"IQC rejection on {doc.name} (PO {po})",
		department="Purchase",
		task_type="Defect / Rejection",
		priority="High",
		reference_doctype="IQC",
		reference_name=doc.name,
		description=(
			f"Incoming Quality Control {doc.name} returned '{outcome}'. "
			f"Raise the vendor debit note / replacement against PO {po} and move "
			f"rejected stock to the RM Rejection store."
		),
		source_event="iqc_reject",
	)


def on_customer_pdi_submit(doc, method=None):
	"""Customer PDI resolved:
	  * Fail -> Rework/Defect task to Production (dispatch stays blocked).
	  * Pass -> the dispatch gate is open; task FG/Dispatch to raise the Delivery
	    Note (and then the Sales Invoice)."""
	so = getattr(doc, "sales_order", "") or ""
	if getattr(doc, "customer_signoff", "") == "Fail":
		create_task(
			title=f"Customer PDI FAIL on {doc.name} (SO {so})",
			department="Production",
			task_type="Defect / Rejection",
			priority="Urgent",
			reference_doctype="Customer PDI",
			reference_name=doc.name,
			description=(
				f"Customer PDI {doc.name} failed for Sales Order {so}. Start rework — "
				f"the lot cannot dispatch until a passed PDI exists."
			),
			source_event="cpdi_fail",
		)
		return
	if getattr(doc, "customer_signoff", "") == "Pass":
		create_task(
			title=f"Dispatch {so} — PDI passed",
			department="FG Stores - Dispatch",
			task_type="Handoff",
			priority="High",
			reference_doctype="Customer PDI",
			reference_name=doc.name,
			description=(
				f"Customer PDI {doc.name} passed for Sales Order {so}. The dispatch "
				f"gate is open: raise the Delivery Note (Dispatch) from the Dispatch FG "
				f"store, then the Sales Invoice. Partial/remaining qty is tracked "
				f"automatically."
			),
			source_event="cpdi_pass",
		)


def on_delivery_note_submit(doc, method=None):
	"""Delivery Note dispatched -> task Accounts to raise the Sales Invoice."""
	sos = sorted({row.against_sales_order for row in doc.items if getattr(row, "against_sales_order", None)})
	so_note = f" (SO {', '.join(sos)})" if sos else ""
	create_task(
		title=f"Raise Sales Invoice for {doc.name}",
		department="Accounts",
		task_type="Handoff",
		priority="High",
		reference_doctype="Delivery Note",
		reference_name=doc.name,
		description=(
			f"Delivery Note {doc.name}{so_note} is dispatched. Raise the Sales Invoice "
			f"(Create → Sales Invoice on the Delivery Note) to bill the customer."
		),
		source_event="dn_to_invoice",
	)


def on_work_order_submit(doc, method=None):
	"""Work Order released -> task the Production line to issue material & build."""
	create_task(
		title=f"Build Work Order {doc.name} ({getattr(doc, 'production_item', '')})",
		department="Production",
		task_type="Handoff",
		priority="High",
		reference_doctype="Work Order",
		reference_name=doc.name,
		description=(
			f"Work Order {doc.name} for {getattr(doc, 'qty', '')} × "
			f"{getattr(doc, 'production_item', '')} is released. Issue material to the "
			f"line, build, and receive FG."
		),
		due_date=getattr(doc, "planned_end_date", None),
		source_event="wo_build",
	)


def on_purchase_receipt_submit(doc, method=None):
	"""GRN posted -> put-away worklist task for RM Stores (capture rack/bin)."""
	from lumirise_custom import defaults as config

	if not config.flag("enable_grn_putaway_task", True):
		return
	create_task(
		title=f"Put away GRN {doc.name}",
		department="Stores - RM",
		task_type="Handoff",
		priority="Medium",
		reference_doctype="Purchase Receipt",
		reference_name=doc.name,
		description=(
			f"Goods received on {doc.name}. Put away into rack/bin locations "
			f"(use Putaway Rules / 'Apply Putaway Rule') and confirm."
		),
		source_event="grn_putaway",
	)


# ---------------------------------------------------------------------------
# Material-flow handoff chain (the back half of the line)
# ---------------------------------------------------------------------------
# Each physical movement in the production-to-dispatch flow auto-creates the
# NEXT responsible team's card, in order, so a kit is never "stuck" on the floor
# without an owner. The chain:
#
#   Material Requisition (Material Transfer)  --> Stores: pick & issue
#   Material Issue to Shop Floor              --> Production: receive at floor
#   Material Receipt (Production)             --> Production: transfer to line
#   Internal Stock Transfer to Line           --> Production: build & receive FG
#   Receipt from Production                    --> FG/Dispatch: move to Dispatch FG
#   FG to Dispatch Transfer                    --> FG/Dispatch: PDI + dispatch
#
# Native ERPNext equivalents (used by the one-click production buttons in
# production.py) are aliased so the chain fires whether the operator runs the
# Focus-named custom Stock Entry Type or the native one. The aliased native
# types only fire when the entry is tied to a Work Order, so unrelated
# Manufacture / Material Transfer for Manufacture entries are ignored.

# stock_entry_type -> next-step card definition.
_SE_FLOW = {
	"Material Issue to Shop Floor": {
		"department": "Production",
		"task_type": "Handoff",
		"priority": "High",
		"title": "Transfer issued material to a line — {ref}",
		"description": (
			"Stores issued the material kit to the shop floor on {ref}. Transfer it "
			"to the relevant production line(s) (Internal Stock Transfer to Line) "
			"against the Work Order — this is what registers material on the line."
		),
		"source_event": "se_issue_to_floor",
	},
	"Internal Stock Transfer to Line": {
		"department": "Production",
		"task_type": "Handoff",
		"priority": "Medium",
		"title": "Build & receive FG for {wo_or_ref}",
		"description": (
			"Material is on the line ({ref}). Build the order and post finished "
			"goods (Receipt from Production) into the Production FG store. RM is "
			"consumed from the line it was transferred to."
		),
		"source_event": "se_transfer_to_line",
	},
	"Receipt from Production": {
		"department": "FG Stores - Dispatch",
		"task_type": "Handoff",
		"priority": "High",
		"title": "Move finished goods to Dispatch FG — {ref}",
		"description": (
			"Finished goods were posted to the Production FG store on {ref}. Move "
			"them to the Dispatch FG store (FG to Dispatch Transfer) and run the "
			"Customer PDI before dispatch."
		),
		"source_event": "se_receipt_from_production",
	},
	"FG to Dispatch Transfer": {
		"department": "FG Stores - Dispatch",
		"task_type": "Handoff",
		"priority": "High",
		"title": "Run Customer PDI + dispatch — {ref}",
		"description": (
			"Finished goods are in the Dispatch FG store ({ref}). Run the Customer "
			"PDI (dispatch gate); once it passes, create the Delivery Note and Sales "
			"Invoice."
		),
		"source_event": "se_fg_to_dispatch",
	},
}

# Native types the production buttons emit, mapped onto the same next-step. These
# only fire when the entry is Work-Order-linked.
_SE_FLOW["Material Transfer for Manufacture"] = _SE_FLOW["Internal Stock Transfer to Line"]
_SE_FLOW["Manufacture"] = _SE_FLOW["Receipt from Production"]
_SE_NATIVE_REQUIRE_WO = {"Material Transfer for Manufacture", "Manufacture"}


def on_material_request_submit(doc, method=None):
	"""Production Material Requisition submitted -> task Stores to pick & issue.

	Only the production-transfer requisition flows to the line; purchase MRs are
	handled by the Indent/PO chain, so they are ignored here."""
	try:
		from lumirise_custom import defaults as config

		if not config.flag("enable_material_flow_tasks", True):
			return
		if (getattr(doc, "material_request_type", "") or "") != "Material Transfer":
			return
		# Production signature: a linked production order or Material For = Production.
		if not (getattr(doc, "production_order", "") or
				(getattr(doc, "material_for", "") or "") == "Production"):
			return
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Lumirise Task Engine: on_material_request_submit gate failed")
		return
	wo = getattr(doc, "production_order", "") or ""
	create_task(
		title=f"Pick & issue material for requisition {doc.name}",
		department="Stores - RM",
		task_type="Handoff",
		priority="High",
		reference_doctype="Material Request",
		reference_name=doc.name,
		description=(
			f"Material Requisition {doc.name}"
			+ (f" (Work Order {wo})" if wo else "")
			+ " is raised. Create the Pick List, pick each item from its rack/bin, "
			"and issue the kit to the shop floor (Material Issue to Shop Floor)."
		),
		due_date=getattr(doc, "schedule_date", None),
		source_event="mr_to_stores",
	)


def on_stock_entry_submit(doc, method=None):
	"""A material-flow Stock Entry posted -> raise the next team's handoff card."""
	try:
		from lumirise_custom import defaults as config

		if not config.flag("enable_material_flow_tasks", True):
			return
		se_type = getattr(doc, "stock_entry_type", "") or getattr(doc, "purpose", "") or ""
		flow = _SE_FLOW.get(se_type)
		if not flow:
			return
		wo = getattr(doc, "work_order", "") or ""
		if se_type in _SE_NATIVE_REQUIRE_WO and not wo:
			return
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Lumirise Task Engine: on_stock_entry_submit gate failed")
		return
	ref = doc.name
	wo_or_ref = wo or doc.name
	create_task(
		title=flow["title"].format(ref=ref, wo_or_ref=wo_or_ref),
		department=flow["department"],
		task_type=flow["task_type"],
		priority=flow["priority"],
		reference_doctype="Stock Entry",
		reference_name=doc.name,
		description=flow["description"].format(ref=ref, wo_or_ref=wo_or_ref),
		source_event=flow["source_event"],
	)


# ---------------------------------------------------------------------------
# Scheduler: escalate overdue tasks to the HOD (the "missed deadline" alert)
# ---------------------------------------------------------------------------
def escalate_overdue_tasks():
	"""Daily: any open task past (due_date + dept escalation_hours) that hasn't
	been escalated -> bump priority, flag escalated, notify + tag the HOD."""
	today = getdate(nowdate())
	candidates = frappe.get_all(
		"Lumirise Task",
		filters=[
			["status", "not in", TERMINAL_STATUSES],
			["escalated", "=", 0],
			["due_date", "is", "set"],
			["due_date", "<", today],
		],
		fields=["name", "title", "department", "hod_user", "due_date"],
	)
	for t in candidates:
		try:
			grace_days = 1
			if t.department:
				hours = frappe.db.get_value(
					"Lumirise Department Map", t.department, "escalation_hours"
				)
				grace_days = max(1, int((hours or 24) / 24))
			if today < add_days(getdate(t.due_date), grace_days):
				continue

			task = frappe.get_doc("Lumirise Task", t.name)
			task.escalated = 1
			if task.priority != "Urgent":
				task.priority = "High" if task.priority in ("Low", "Medium") else "Urgent"
			task.flags.ignore_permissions = True
			task.save(ignore_permissions=True)

			hod = _enabled_user(t.hod_user)
			if hod:
				_assign(t.name, hod, write=False)
				_mention(task, [hod])
			task.add_comment(
				"Comment",
				text=f"⚠️ Overdue since {t.due_date} — auto-escalated to the HOD.",
			)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(frappe.get_traceback(), f"Lumirise Task Engine: escalate failed for {t.name}")
