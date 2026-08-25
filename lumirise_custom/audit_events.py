"""Structured audit-event helper for later registry-driven actions."""

import json
from collections.abc import Mapping, Sequence

import frappe
from frappe.utils import now_datetime

from lumirise_custom.action_registry import get_action

AUDIT_PREFIX = "LUMIRISE_ACTION_AUDIT:"


def build_audit_event(
	action_id: str,
	*,
	source_doctype: str,
	source_name: str,
	actor: str | None = None,
	reason_code: str | None = None,
	reason_note: str | None = None,
	before: Mapping | None = None,
	after: Mapping | None = None,
	downstream_documents: Sequence[Mapping] | None = None,
	occurred_on=None,
) -> dict:
	"""Build a stable, JSON-serializable event without writing to the database."""
	contract = get_action(action_id)
	if contract.reason_required and (not reason_code or not reason_note):
		frappe.throw("This action requires both a stable reason code and a reason note.")
	return {
		"schema_version": 1,
		"action_id": contract.action_id,
		"source_doctype": source_doctype,
		"source_name": source_name,
		"actor": actor or frappe.session.user,
		"occurred_on": str(occurred_on or now_datetime()),
		"reason_code": reason_code,
		"reason_note": reason_note,
		"before": dict(before or {}),
		"after": dict(after or {}),
		"downstream_documents": [dict(row) for row in (downstream_documents or ())],
	}


def record_audit_event(action_id: str, *, source_doctype: str, source_name: str, **values) -> dict:
	"""Append a structured comment to a permitted source document."""
	doc = frappe.get_doc(source_doctype, source_name)
	doc.check_permission("read")
	event = build_audit_event(
		action_id,
		source_doctype=source_doctype,
		source_name=source_name,
		**values,
	)
	doc.add_comment("Info", f"{AUDIT_PREFIX}{json.dumps(event, sort_keys=True)}")
	return event

