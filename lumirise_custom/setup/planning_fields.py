"""Production Planning fields on STANDARD doctypes (WP-P.1).

For the Production Planning & Scheduling module (2026-07-08 client call):
- Item.lr_cph        — per-item Capacity/Day, from the PPC plan sheet's CPH column.
                       Line-days for a slice = qty / CPH.
- Sales Order.lr_priority / lr_urgent_percent — sales-assigned scheduling inputs:
                       a priority number and the % of the order to run as urgent.

Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDS = {
	"Item": [
		dict(
			fieldname="lr_cph",
			label="Capacity / Day (CPH)",
			fieldtype="Float",
			insert_after="lead_time_days",
			module="Lumirise Custom",
			description="Units this FG produces per day on one line (from the PPC plan sheet). Line-days for a slice = qty / CPH.",
		),
	],
	"Sales Order": [
		dict(
			fieldname="lr_priority",
			label="Production Priority",
			fieldtype="Int",
			insert_after="delivery_date",
			in_standard_filter=1,
			in_list_view=1,
			module="Lumirise Custom",
			description="Sales-assigned priority for production scheduling (1 = highest).",
		),
		dict(
			fieldname="lr_urgent_percent",
			label="Urgent %",
			fieldtype="Percent",
			default="0",
			insert_after="lr_priority",
			module="Lumirise Custom",
			description="Portion of this order to schedule as urgent — produced ahead of all normal slices.",
		),
	],
}


def create_planning_fields():
	create_custom_fields(FIELDS, update=True)
