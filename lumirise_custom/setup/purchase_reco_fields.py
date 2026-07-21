"""BOM Reconciliation tab on the Purchase Order.

Two read-only custom fields that host the buyer's BOM-tally + per-model price-split
tool (rendered by public/js/purchase_order.js):
  - lr_bom_reco_tab  : a Tab Break ("BOM Reconciliation")
  - lr_bom_reco_html : the HTML the JS fills in

Placed at the END of the form (after the last non-Lumirise field) so the new tab
sits after the standard tabs. Idempotent — safe to run on every migrate.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

OWN_FIELDS = {"lr_bom_reco_tab", "lr_bom_reco_html"}


def create_purchase_reco_fields():
	meta = frappe.get_meta("Purchase Order")
	candidates = [f.fieldname for f in meta.fields if f.fieldname not in OWN_FIELDS]
	last_field = candidates[-1] if candidates else "items"
	po_fields = [
		# Import vs Domestic flag on the same PO screen (Rishitha, 2026-07-20
		# ~01:13:10 "same screen, a flag whether it's import or domestic; currency
		# shown here"). Informational + filterable — the currency still drives costing.
		dict(
			fieldname="lr_order_type",
			label="Order Type",
			fieldtype="Select",
			options="Domestic\nImport",
			default="Domestic",
			insert_after="supplier",
			in_standard_filter=1,
			module="Lumirise Custom",
			translatable=0,
			description="Domestic (INR) or Import (foreign-currency) purchase. Informational flag; the PO currency drives the actual costing/exchange rate.",
		),
		dict(
			fieldname="lr_bom_reco_tab",
			label="BOM Reconciliation",
			fieldtype="Tab Break",
			insert_after=last_field,
			module="Lumirise Custom",
		),
		dict(
			fieldname="lr_bom_reco_html",
			label="BOM Reconciliation",
			fieldtype="HTML",
			insert_after="lr_bom_reco_tab",
			module="Lumirise Custom",
		),
	]
	# Purchase Plan: an Indent-vs-Order balance table right after the items table
	# (Indent Qty − Going-to-Order Qty = Indent Balance, per item).
	plan_fields = [
		dict(
			fieldname="lr_balance_sb",
			label="Indent vs Order Balance",
			fieldtype="Section Break",
			insert_after="items",
			module="Lumirise Custom",
		),
		dict(
			fieldname="lr_indent_balance_html",
			label="Indent Balance",
			fieldtype="HTML",
			insert_after="lr_balance_sb",
			module="Lumirise Custom",
		),
	]
	create_custom_fields(
		{"Purchase Order": po_fields, "Purchase Plan": plan_fields}, update=True)
