"""Purchase Plan supplier controls (Sai walkthrough 2026-06-30, req 6.2).

  - lr_global_supplier    : a parent-level Supplier that cascades to every line
                            (buyer can still override the supplier per item).
  - lr_supplier_split_sb  : Section Break ("Supplier-wise Split")
  - lr_supplier_split_html: one read-only table per distinct supplier, listing the
                            items that will go to that supplier's PO — rendered by
                            public/.../purchase_plan.js.

Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def create_purchase_plan_supplier_fields():
	fields = [
		dict(
			fieldname="lr_global_supplier",
			label="Global Supplier (applies to all lines)",
			fieldtype="Link",
			options="Supplier",
			insert_after="branch",
			module="Lumirise Custom",
			description="Sets the supplier on every line. Override the supplier on an "
			"individual line in the items table where a different vendor is needed.",
		),
		dict(
			fieldname="lr_supplier_split_sb",
			label="Supplier-wise Split",
			fieldtype="Section Break",
			insert_after="lr_indent_balance_html",
			module="Lumirise Custom",
			collapsible=1,
		),
		dict(
			fieldname="lr_supplier_split_html",
			label="Supplier-wise Split",
			fieldtype="HTML",
			insert_after="lr_supplier_split_sb",
			module="Lumirise Custom",
		),
		# Kit calculator (change-list 6.3): complete kits vs loose parts per model.
		dict(
			fieldname="lr_kit_calc_sb",
			label="Kit Calculator",
			fieldtype="Section Break",
			insert_after="lr_supplier_split_html",
			module="Lumirise Custom",
			collapsible=1,
		),
		dict(
			fieldname="lr_kit_calc_html",
			label="Kit Calculator",
			fieldtype="HTML",
			insert_after="lr_kit_calc_sb",
			module="Lumirise Custom",
		),
	]
	create_custom_fields({"Purchase Plan": fields}, update=True)
