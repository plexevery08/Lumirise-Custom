# Health Check Trend — run history of the daily self-test, newest first. The
# "is the machine healthy over time?" view (green/amber/red per day + counts).

import frappe
from frappe import _


def execute(filters=None):
	return get_columns(), get_data(filters or {})


def get_columns():
	return [
		{"label": _("Run"), "fieldname": "name", "fieldtype": "Link", "options": "Health Check Run", "width": 160},
		{"label": _("Run At"), "fieldname": "run_datetime", "fieldtype": "Datetime", "width": 160},
		{"label": _("Overall"), "fieldname": "overall_status", "fieldtype": "Data", "width": 90},
		{"label": _("Pass"), "fieldname": "pass_count", "fieldtype": "Int", "width": 70},
		{"label": _("Warn"), "fieldname": "warn_count", "fieldtype": "Int", "width": 70},
		{"label": _("Fail"), "fieldname": "fail_count", "fieldtype": "Int", "width": 70},
		{"label": _("Synthetic"), "fieldname": "synthetic_ran", "fieldtype": "Check", "width": 80},
		{"label": _("Summary"), "fieldname": "summary", "fieldtype": "Data", "width": 420},
	]


def get_data(filters):
	return frappe.get_all(
		"Health Check Run",
		fields=[
			"name",
			"run_datetime",
			"overall_status",
			"pass_count",
			"warn_count",
			"fail_count",
			"synthetic_ran",
			"summary",
		],
		order_by="run_datetime desc",
		limit_page_length=90,
	)
