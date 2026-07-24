# Bitrix24 one-way sync: every Lumirise Task / Lumirise Job Card change is mirrored
# to a Bitrix24 task via the client's inbound webhook (tasks.task.add / .update).
#
# Design rules:
#   - NEVER block the ERP transaction: hooks only enqueue; the HTTP call runs in a
#     background job with its own retry. Bitrix being down cannot stop production.
#   - No-op unless Bitrix Sync Settings.enabled — safe to ship before the client
#     shares their webhook URL.
#   - Bitrix Task Map holds the ERP-doc -> Bitrix-task-ID join; rows in Error are
#     retried by the daily scheduler job.

import json

import frappe
import requests
from frappe.utils import now_datetime

# ERP status -> Bitrix24 task STATUS (2 pending, 3 in progress, 5 completed, 6 deferred)
TASK_STATUS = {
	"Open": 2, "In Progress": 3, "Blocked": 6, "Done": 5, "Cancelled": 5,
	# Lumirise Job Card
	"Met": 5, "Missed": 6,
}


def _settings():
	return frappe.get_cached_doc("Bitrix Sync Settings")


def enqueue_push(doc, method=None):
	"""doc_events entry point for Lumirise Task and Lumirise Job Card."""
	try:
		s = _settings()
	except Exception:
		return  # settings doctype not migrated yet
	if not s.enabled or not s.webhook_url:
		return
	frappe.enqueue(
		"lumirise_custom.bitrix_sync.push_doc",
		queue="short", job_id=f"bitrix-{doc.doctype}-{doc.name}",
		deduplicate=True, doctype=doc.doctype, name=doc.name,
	)


def _payload(doc, s):
	title = doc.get("title") or f"{doc.doctype} {doc.name}"
	if doc.doctype == "Lumirise Job Card":
		title = f"Job Card {doc.name}"
	desc = (doc.get("description") or "") + f"\n\nERPNext: {frappe.utils.get_url_to_form(doc.doctype, doc.name)}"
	return {
		"TITLE": title[:250],
		"DESCRIPTION": desc,
		"RESPONSIBLE_ID": s.default_responsible_id or "1",
		"STATUS": TASK_STATUS.get(doc.get("status"), 2),
	}


def push_doc(doctype, name):
	s = _settings()
	if not s.enabled or not s.webhook_url:
		return
	doc = frappe.get_doc(doctype, name)
	row_name = frappe.db.exists("Bitrix Task Map", {"erp_doctype": doctype, "erp_name": name})
	row = frappe.get_doc("Bitrix Task Map", row_name) if row_name else frappe.get_doc(
		{"doctype": "Bitrix Task Map", "erp_doctype": doctype, "erp_name": name, "status": "Pending"}
	)
	fields = _payload(doc, s)
	try:
		if row.bitrix_task_id:
			resp = requests.post(f"{s.webhook_url}tasks.task.update.json",
				json={"taskId": row.bitrix_task_id, "fields": fields}, timeout=20)
		else:
			resp = requests.post(f"{s.webhook_url}tasks.task.add.json",
				json={"fields": fields}, timeout=20)
		resp.raise_for_status()
		data = resp.json()
		if "error" in data:
			raise Exception(f"Bitrix error: {data.get('error_description') or data['error']}")
		if not row.bitrix_task_id:
			row.bitrix_task_id = str(data["result"]["task"]["id"])
		row.status = "Synced"
		row.last_synced = now_datetime()
		row.last_error = None
	except Exception as e:
		row.status = "Error"
		row.last_error = str(e)[:500]
		frappe.db.set_value("Bitrix Sync Settings", None, "last_error",
			f"{doctype} {name}: {str(e)[:400]}")
	row.save(ignore_permissions=True)
	frappe.db.commit()


def retry_failed_pushes():
	"""Daily scheduler entry: re-enqueue every Error row."""
	try:
		s = _settings()
	except Exception:
		return
	if not s.enabled or not s.webhook_url:
		return
	for r in frappe.get_all("Bitrix Task Map", filters={"status": "Error"},
			fields=["erp_doctype", "erp_name"]):
		frappe.enqueue("lumirise_custom.bitrix_sync.push_doc", queue="short",
			doctype=r.erp_doctype, name=r.erp_name)
