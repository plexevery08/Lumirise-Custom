"""Line Transfer tab on the Work Order.

Two read-only custom fields that host the per-line qty breakdown (rendered by
public/js/work_order.js via production.line_transfer_breakdown):
  - lr_line_transfer_tab   : a Tab Break ("Line Transfer")
  - lr_line_transfer_html  : the HTML the JS fills in

Placed at the END of the form so the new tab sits after the standard tabs.
Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

OWN_FIELDS = {"lr_line_transfer_tab", "lr_line_transfer_html"}


def create_wo_line_transfer_fields():
	meta = frappe.get_meta("Work Order")
	candidates = [f.fieldname for f in meta.fields if f.fieldname not in OWN_FIELDS]
	last_field = candidates[-1] if candidates else "required_items"
	wo_fields = [
		dict(
			fieldname="lr_line_transfer_tab",
			label="Line Transfer",
			fieldtype="Tab Break",
			insert_after=last_field,
			module="Lumirise Custom",
		),
		dict(
			fieldname="lr_line_transfer_html",
			label="Line Transfer Breakdown",
			fieldtype="HTML",
			insert_after="lr_line_transfer_tab",
			module="Lumirise Custom",
		),
	]
	create_custom_fields({"Work Order": wo_fields}, update=True)
