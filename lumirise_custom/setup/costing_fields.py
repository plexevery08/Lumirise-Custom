"""Item / BOM costing custom fields — restored from the live-site baseline.

Field names match the Frappe Cloud site exactly (including the trailing
underscore on custom_interest_) so specs, reports, and an eventual live push
stay compatible. Spec: Item_BOM_Costing.md in the imported technical repo.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _layer(fieldname, label, insert_after):
	"""One layered cost: percent input + base/value/total (read-only)."""
	return [
		dict(fieldname=fieldname, label=label, fieldtype="Percent", insert_after=insert_after),
		dict(fieldname=f"{fieldname.rstrip('_')}_base", label=f"{label} Base",
			fieldtype="Currency", read_only=1, precision="3",
			insert_after=fieldname),
		dict(fieldname=f"{fieldname.rstrip('_')}_value", label=f"{label} Value",
			fieldtype="Currency", read_only=1, precision="3",
			insert_after=f"{fieldname.rstrip('_')}_base"),
		dict(fieldname=f"{fieldname.rstrip('_')}_total", label=f"{label} Total",
			fieldtype="Currency", read_only=1, precision="3",
			insert_after=f"{fieldname.rstrip('_')}_value"),
	]


ITEM_FIELDS = [
	dict(fieldname="custom_import_costing_section", label="Import Costing",
		fieldtype="Section Break", insert_after="valuation_rate", collapsible=1),
	dict(fieldname="custom_price_in_rmb", label="Price In RMB",
		fieldtype="Currency", precision="3", insert_after="custom_import_costing_section",
		allow_on_submit=0),
	dict(fieldname="custom_rmb_to_inr_rate", label="RMB to INR Rate",
		fieldtype="Float", precision="4", insert_after="custom_price_in_rmb"),
	dict(fieldname="custom_custom_duty", label="Custom Duty %",
		fieldtype="Percent", insert_after="custom_rmb_to_inr_rate"),
	dict(fieldname="custom_import_costing_col", fieldtype="Column Break",
		insert_after="custom_custom_duty"),
	dict(fieldname="custom_price_in_inr", label="Price In INR",
		fieldtype="Currency", read_only=1, precision="3", insert_after="custom_import_costing_col"),
	dict(fieldname="custom_basic_custom_duty", label="Basic Custom Duty",
		fieldtype="Currency", read_only=1, precision="3", insert_after="custom_price_in_inr"),
]

BOM_FIELDS = (
	[
		dict(fieldname="custom_costing_section", label="Lumirise Costing",
			fieldtype="Section Break", insert_after="items", collapsible=1),
		dict(fieldname="custom_bom_type", label="BOM Type", fieldtype="Select",
			options="Parent BOM\nSub BOM", default="Parent BOM",
			insert_after="custom_costing_section", allow_on_submit=1,
			in_standard_filter=1),
		dict(fieldname="custom_raw_materials_total", label="Raw Materials Total",
			fieldtype="Currency", read_only=1, precision="3", insert_after="custom_bom_type"),
		dict(fieldname="custom_conversion_cost", label="Conversion Cost",
			fieldtype="Currency", precision="3", insert_after="custom_raw_materials_total",
			allow_on_submit=1,
			description="Sub BOM only: added on top of raw materials for the sub-assembly total."),
		dict(fieldname="custom_sub_bom_total", label="Sub BOM Total",
			fieldtype="Currency", read_only=1, precision="3", insert_after="custom_conversion_cost"),
		dict(fieldname="custom_costing_col_a", fieldtype="Column Break",
			insert_after="custom_sub_bom_total"),
		dict(fieldname="custom_inward_transport_cost", label="Inward Transport Cost",
			fieldtype="Currency", precision="3", insert_after="custom_costing_col_a",
			allow_on_submit=1, depends_on='eval:doc.custom_bom_type=="Parent BOM"'),
		dict(fieldname="custom_factory_overheads", label="Factory Overheads",
			fieldtype="Currency", precision="3", insert_after="custom_inward_transport_cost",
			allow_on_submit=1, depends_on='eval:doc.custom_bom_type=="Parent BOM"'),
		dict(fieldname="custom_layered_costs_section", label="Layered Costs",
			fieldtype="Section Break", insert_after="custom_factory_overheads",
			collapsible=1, depends_on='eval:doc.custom_bom_type=="Parent BOM"'),
	]
	+ _layer("custom_dollar_rate_fluctuations", "Dollar Rate Fluctuations",
		"custom_layered_costs_section")
	+ _layer("custom_interest_", "Interest", "custom_dollar_rate_fluctuations_total")
	+ _layer("custom_miscellaneous", "Miscellaneous", "custom_interest_total")
	+ _layer("custom_replacement", "Replacement", "custom_miscellaneous_total")
	+ _layer("custom_marketing_expenses", "Marketing Expenses", "custom_replacement_total")
	+ [
		dict(fieldname="custom_final_cost_section", label="Final Cost & MOQ Pricing",
			fieldtype="Section Break", insert_after="custom_marketing_expenses_total",
			depends_on='eval:doc.custom_bom_type=="Parent BOM"'),
		dict(fieldname="custom_bom_cost", label="BOM Cost",
			fieldtype="Currency", read_only=1, precision="3", bold=1,
			insert_after="custom_final_cost_section"),
		dict(fieldname="custom_1k_moq_percentage", label="1K MOQ %",
			fieldtype="Percent", insert_after="custom_bom_cost", allow_on_submit=1),
		dict(fieldname="custom_1k_moq_price", label="1K MOQ Price",
			fieldtype="Currency", read_only=1, precision="3", insert_after="custom_1k_moq_percentage"),
		dict(fieldname="custom_3k_moq_percentage", label="3K MOQ %",
			fieldtype="Percent", insert_after="custom_1k_moq_price", allow_on_submit=1),
		dict(fieldname="custom_3k_moq_price", label="3K MOQ Price",
			fieldtype="Currency", read_only=1, precision="3", insert_after="custom_3k_moq_percentage"),
		dict(fieldname="custom_moq_col", fieldtype="Column Break",
			insert_after="custom_3k_moq_price"),
		dict(fieldname="custom_6k_moq_percentage", label="6K MOQ %",
			fieldtype="Percent", insert_after="custom_moq_col", allow_on_submit=1),
		dict(fieldname="custom_6k_moq_price", label="6K MOQ Price",
			fieldtype="Currency", read_only=1, precision="3", insert_after="custom_6k_moq_percentage"),
		dict(fieldname="custom_10k_moq_percentage", label="10K MOQ %",
			fieldtype="Percent", insert_after="custom_6k_moq_price", allow_on_submit=1),
		dict(fieldname="custom_10k_moq_price", label="10K MOQ Price",
			fieldtype="Currency", read_only=1, precision="3", insert_after="custom_10k_moq_percentage"),
	]
)


QUOTATION_FIELDS = [
	# One-way reference: the Quotation knows which Price Sheet produced it.
	dict(fieldname="custom_price_sheet", label="Price Sheet", fieldtype="Data",
		read_only=1, no_copy=1, insert_after="naming_series", in_standard_filter=1),
]


def create_costing_fields():
	create_custom_fields(
		{"Item": ITEM_FIELDS, "BOM": BOM_FIELDS, "Quotation": QUOTATION_FIELDS},
		update=True,
	)
