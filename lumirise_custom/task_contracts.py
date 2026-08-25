"""Stable contracts for operational tasks.

The module intentionally contains no whitelisted UI action.  It defines the
Phase 0 data semantics which later queue pages and action registries must use.
"""

from __future__ import annotations

from typing import Literal

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

TASK_STATUSES = ("Open", "In Progress", "Blocked", "Done", "Cancelled")
TERMINAL_STATUSES = frozenset({"Done", "Cancelled"})
SEVERITIES = ("Low", "Medium", "High", "Critical")

# Codes are persisted; labels may be translated or changed without migrating data.
BLOCKER_REASONS = {
	"approval_pending": "Approval pending",
	"capacity_unavailable": "Capacity unavailable",
	"data_missing": "Required data missing",
	"dependency_pending": "Dependency pending",
	"material_shortage": "Material shortage",
	"quality_hold": "Quality hold",
	"vendor_delay": "Vendor delay",
	"other": "Other",
}

RESOLUTION_REASONS = {
	"completed": "Completed",
	"cancelled": "Cancelled",
	"duplicate": "Duplicate",
	"not_required": "No longer required",
	"superseded": "Superseded",
	"other": "Other",
}

PRIORITY_TO_SEVERITY = {
	"Low": "Low",
	"Medium": "Medium",
	"High": "High",
	"Urgent": "Critical",
}


def task_view(status: str, review_on=None, *, now=None) -> Literal["active", "waiting", "blocked", "closed"]:
	"""Classify a persisted state for queue views without inventing a new status.

	Waiting is ``Blocked`` with a future review time.  A blocked task whose review
	is due (or absent) returns to the actionable Blocked view.
	"""
	if status in TERMINAL_STATUSES:
		return "closed"
	if status != "Blocked":
		return "active"
	if review_on and get_datetime(review_on) > get_datetime(now or now_datetime()):
		return "waiting"
	return "blocked"


def normalize_task(doc) -> None:
	"""Apply additive Phase 0 defaults and validate stable code fields."""
	if doc.status not in TASK_STATUSES:
		frappe.throw(_("Invalid task status: {0}").format(doc.status), frappe.ValidationError)

	if not doc.severity:
		doc.severity = PRIORITY_TO_SEVERITY.get(doc.priority, "Medium")
	if doc.severity not in SEVERITIES:
		frappe.throw(_("Invalid task severity: {0}").format(doc.severity), frappe.ValidationError)

	# due_on is canonical.  due_date remains a derived compatibility field while
	# existing reports and integrations are migrated gradually.
	if doc.due_on:
		doc.due_date = getdate(doc.due_on)
	elif doc.due_date:
		doc.due_on = get_datetime(f"{getdate(doc.due_date)} 23:59:59")

	if not doc.source_department and doc.department:
		doc.source_department = doc.department

	if doc.blocker_code and doc.blocker_code not in BLOCKER_REASONS:
		frappe.throw(_("Unknown blocker code: {0}").format(doc.blocker_code), frappe.ValidationError)
	if doc.resolution_code and doc.resolution_code not in RESOLUTION_REASONS:
		frappe.throw(_("Unknown resolution code: {0}").format(doc.resolution_code), frappe.ValidationError)

	if doc.status == "Blocked" and not doc.blocker_code:
		frappe.throw(_("A blocker code is required when a task is Blocked."), frappe.ValidationError)
	if doc.status == "Blocked" and not doc.blocker_reason:
		frappe.throw(_("A blocker reason is required when a task is Blocked."), frappe.ValidationError)

	if doc.status in TERMINAL_STATUSES:
		if not doc.resolution_code:
			doc.resolution_code = "completed" if doc.status == "Done" else "cancelled"
		if not doc.resolved_on:
			doc.resolved_on = now_datetime()
		if not doc.resolved_by:
			doc.resolved_by = frappe.session.user
	else:
		doc.resolved_on = None
		doc.resolved_by = None


def synchronize_owner_assignment(task, previous_owner: str | None) -> None:
	"""Atomically align owner_user, its active ToDo, and its writable DocShare.

	This runs in the same database transaction as the task save.  Oversight users
	retain shares, but only the accountable owner receives an active assignment.
	"""
	new_owner = task.owner_user
	if previous_owner == new_owner:
		return

	from frappe.desk.form.assign_to import add as add_assignment
	from frappe.desk.form.assign_to import remove as remove_assignment

	if previous_owner:
		remove_assignment(task.doctype, task.name, previous_owner, ignore_permissions=True)
		if previous_owner not in {task.supervisor_user, task.hod_user}:
			frappe.share.remove(
				task.doctype,
				task.name,
				previous_owner,
				flags={"ignore_permissions": True},
			)

	if new_owner:
		add_assignment(
			{
				"assign_to": [new_owner],
				"doctype": task.doctype,
				"name": task.name,
				"description": task.title,
				"notify": 1,
			},
			ignore_permissions=True,
		)
		frappe.share.add(
			task.doctype,
			task.name,
			new_owner,
			write=1,
			flags={"ignore_share_permission": True},
		)

