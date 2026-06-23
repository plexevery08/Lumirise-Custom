# Open Health Failures — the latest self-test run's failing/warning checks with,
# for each, the plain-English remediation (the improvement to make). The daily
# "punch list": what is broken right now and how to fix it.

import frappe
from frappe import _


def execute(filters=None):
	return get_columns(), get_data()


def get_columns():
	return [
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 80},
		{"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 120},
		{"label": _("Check"), "fieldname": "title", "fieldtype": "Data", "width": 280},
		{"label": _("Detail"), "fieldname": "detail", "fieldtype": "Data", "width": 360},
		{"label": _("Remediation (the fix)"), "fieldname": "remediation", "fieldtype": "Data", "width": 440},
		{"label": _("Evidence"), "fieldname": "evidence", "fieldtype": "Data", "width": 240},
	]


def get_data():
	last = frappe.get_all(
		"Health Check Run", fields=["name"], order_by="run_datetime desc", limit_page_length=1
	)
	if not last:
		return []
	doc = frappe.get_doc("Health Check Run", last[0].name)
	rows = []
	for r in doc.results:
		if r.status in ("fail", "warn"):
			rows.append(
				{
					"status": r.status,
					"stage": r.stage,
					"title": r.title,
					"detail": r.detail,
					"remediation": r.remediation,
					"evidence": r.evidence,
				}
			)
	return rows
