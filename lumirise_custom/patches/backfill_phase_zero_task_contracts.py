"""Additive Phase 0 task-contract backfill with an inspectable dry-run plan."""

from __future__ import annotations

import frappe
from frappe.utils import get_datetime

from lumirise_custom.task_contracts import PRIORITY_TO_SEVERITY, TERMINAL_STATUSES


def build_backfill_plan() -> list[dict]:
	"""Return exact row-level updates without mutating the database."""
	rows = frappe.get_all(
		"Lumirise Task",
		fields=[
			"name",
			"status",
			"priority",
			"department",
			"due_date",
			"due_on",
			"severity",
			"source_department",
			"blocker_code",
			"blocker_reason",
			"completed_on",
			"resolved_on",
			"resolved_by",
			"modified",
			"modified_by",
		],
		order_by="name",
	)

	plan = []
	for row in rows:
		updates = {}
		if not row.severity:
			updates["severity"] = PRIORITY_TO_SEVERITY.get(row.priority, "Medium")
		if row.due_date and not row.due_on:
			updates["due_on"] = get_datetime(f"{row.due_date} 23:59:59")
		if row.department and not row.source_department:
			updates["source_department"] = row.department

		# Preserve legacy blocked work without inventing a business-specific cause.
		# Operators can replace this explicit compatibility value later.
		if row.status == "Blocked":
			if not row.blocker_code:
				updates["blocker_code"] = "other"
			if not row.blocker_reason:
				updates["blocker_reason"] = "Blocked before the Phase 0 task contract was introduced."

		if row.status in TERMINAL_STATUSES:
			if not row.resolved_on:
				updates["resolved_on"] = row.completed_on or row.modified
			if not row.resolved_by:
				updates["resolved_by"] = row.modified_by

		if updates:
			plan.append({"name": row.name, "updates": updates})

	return plan


def execute(dry_run: bool = False):
	"""Apply only missing compatibility values; safe to run repeatedly."""
	plan = build_backfill_plan()
	if dry_run:
		return plan

	for change in plan:
		frappe.db.set_value(
			"Lumirise Task",
			change["name"],
			change["updates"],
			update_modified=False,
		)

	frappe.logger("lumirise_custom").info("Phase 0 task contract backfill updated %s task(s)", len(plan))
	return len(plan)


def pending_count() -> int:
	"""Small release-gate helper: zero proves the additive backfill is idempotent."""
	return len(build_backfill_plan())


def migration_status() -> dict[str, int]:
	"""CLI-friendly status (a dict is printed even when the count is zero)."""
	return {"pending_task_backfills": pending_count()}
