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
		dict(
			fieldname=f"{fieldname.rstrip('_')}_base",
			label=f"{label} Base",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after=fieldname,
		),
		dict(
			fieldname=f"{fieldname.rstrip('_')}_value",
			label=f"{label} Value",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after=f"{fieldname.rstrip('_')}_base",
		),
		dict(
			fieldname=f"{fieldname.rstrip('_')}_total",
			label=f"{label} Total",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after=f"{fieldname.rstrip('_')}_value",
		),
	]


ITEM_FIELDS = [
	dict(
		fieldname="custom_import_costing_section",
		label="Import Costing",
		fieldtype="Section Break",
		insert_after="valuation_rate",
		collapsible=1,
	),
	dict(
		fieldname="custom_price_in_rmb",
		label="Price In RMB",
		fieldtype="Currency",
		precision="3",
		insert_after="custom_import_costing_section",
		allow_on_submit=0,
	),
	dict(
		fieldname="custom_rmb_to_inr_rate",
		label="RMB to INR Rate Override",
		fieldtype="Float",
		precision="4",
		insert_after="custom_price_in_rmb",
		description="Used only when global-rate enforcement is off or the global rate is blank.",
	),
	dict(
		fieldname="custom_custom_duty",
		label="Custom Duty %",
		fieldtype="Percent",
		insert_after="custom_rmb_to_inr_rate",
	),
	dict(fieldname="custom_import_costing_col", fieldtype="Column Break", insert_after="custom_custom_duty"),
	dict(
		fieldname="custom_effective_rmb_to_inr_rate",
		label="Effective RMB to INR Rate",
		fieldtype="Float",
		read_only=1,
		precision="4",
		insert_after="custom_import_costing_col",
	),
	dict(
		fieldname="custom_price_in_inr",
		label="Price In INR",
		fieldtype="Currency",
		read_only=1,
		precision="3",
		insert_after="custom_effective_rmb_to_inr_rate",
	),
	dict(
		fieldname="custom_basic_custom_duty",
		label="Basic Custom Duty",
		fieldtype="Currency",
		read_only=1,
		precision="3",
		insert_after="custom_price_in_inr",
	),
	dict(
		fieldname="custom_cost_source_section",
		label="Resolved Commercial Cost",
		fieldtype="Section Break",
		insert_after="custom_basic_custom_duty",
		collapsible=1,
	),
	dict(
		fieldname="custom_costing_rate",
		label="Commercial Costing Rate",
		fieldtype="Currency",
		read_only=1,
		precision="3",
		bold=1,
		insert_after="custom_cost_source_section",
		description="Authoritative per-unit rate used by Lumirise BOM costing; separate from inventory valuation.",
	),
	dict(
		fieldname="custom_costing_rate_source",
		label="Cost Source",
		fieldtype="Data",
		read_only=1,
		insert_after="custom_costing_rate",
	),
	dict(
		fieldname="custom_costing_rate_reference",
		label="Cost Reference",
		fieldtype="Data",
		read_only=1,
		insert_after="custom_costing_rate_source",
	),
	dict(
		fieldname="custom_cost_source_col",
		fieldtype="Column Break",
		insert_after="custom_costing_rate_reference",
	),
	dict(
		fieldname="custom_last_purchase_cost",
		label="Last Purchase Cost",
		fieldtype="Currency",
		read_only=1,
		precision="3",
		insert_after="custom_cost_source_col",
		description="Fallback captured from the latest submitted Purchase Receipt.",
	),
	dict(
		fieldname="custom_costing_rate_updated_on",
		label="Cost Resolved On",
		fieldtype="Datetime",
		read_only=1,
		insert_after="custom_last_purchase_cost",
	),
]


BOM_ITEM_FIELDS = [
	dict(
		fieldname="custom_cost_source",
		label="Lumirise Cost Source",
		fieldtype="Data",
		read_only=1,
		insert_after="rate",
		in_list_view=1,
	),
	dict(
		fieldname="custom_cost_reference",
		label="Cost Reference",
		fieldtype="Data",
		read_only=1,
		insert_after="custom_cost_source",
	),
]

BOM_FIELDS = (
	[  # noqa: RUF005 - layered field groups are intentionally assembled in business order.
		dict(
			fieldname="custom_costing_section",
			label="Lumirise Costing",
			fieldtype="Section Break",
			insert_after="items",
			collapsible=1,
		),
		dict(
			fieldname="custom_bom_type",
			label="BOM Type",
			fieldtype="Select",
			options="Parent BOM\nSub BOM",
			default="Parent BOM",
			insert_after="custom_costing_section",
			allow_on_submit=1,
			in_standard_filter=1,
		),
		dict(
			fieldname="custom_raw_materials_batch_total",
			label="Raw Materials Batch Total",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after="custom_bom_type",
			description="Sum of BOM Item amounts for the full BOM quantity.",
		),
		dict(
			fieldname="custom_raw_materials_total",
			label="Raw Materials Total",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after="custom_raw_materials_batch_total",
			description="Raw Materials Batch Total divided by BOM Quantity (per finished unit).",
		),
		dict(
			fieldname="custom_conversion_cost",
			label="Conversion Cost",
			fieldtype="Currency",
			precision="3",
			insert_after="custom_raw_materials_total",
			allow_on_submit=1,
			description="Per finished unit. Sub BOM only: added to raw materials after quantity normalization.",
		),
		dict(
			fieldname="custom_sub_bom_total",
			label="Unit Roll-up Cost",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after="custom_conversion_cost",
			description="Final per-unit cost consumed by a parent BOM, for both Parent and Sub BOMs.",
		),
		dict(
			fieldname="custom_costing_status",
			label="Costing Status",
			fieldtype="Select",
			options="Complete\nMissing Costs",
			read_only=1,
			insert_after="custom_sub_bom_total",
		),
		dict(
			fieldname="custom_missing_cost_items",
			label="Missing Cost Items",
			fieldtype="Small Text",
			read_only=1,
			insert_after="custom_costing_status",
			depends_on='eval:doc.custom_costing_status=="Missing Costs"',
		),
		dict(
			fieldname="custom_costing_col_a",
			fieldtype="Column Break",
			insert_after="custom_missing_cost_items",
		),
		dict(
			fieldname="custom_inward_transport_cost",
			label="Inward Transport Cost",
			fieldtype="Currency",
			precision="3",
			insert_after="custom_costing_col_a",
			allow_on_submit=1,
			depends_on='eval:doc.custom_bom_type=="Parent BOM"',
			description="Per finished unit.",
		),
		dict(
			fieldname="custom_factory_overheads",
			label="Factory Overheads",
			fieldtype="Currency",
			precision="3",
			insert_after="custom_inward_transport_cost",
			allow_on_submit=1,
			depends_on='eval:doc.custom_bom_type=="Parent BOM"',
			description="Per finished unit.",
		),
		dict(
			fieldname="custom_layered_costs_section",
			label="Layered Costs",
			fieldtype="Section Break",
			insert_after="custom_factory_overheads",
			collapsible=1,
			depends_on='eval:doc.custom_bom_type=="Parent BOM"',
		),
	]
	+ _layer("custom_dollar_rate_fluctuations", "Dollar Rate Fluctuations", "custom_layered_costs_section")
	+ _layer("custom_interest_", "Interest", "custom_dollar_rate_fluctuations_total")
	+ _layer("custom_miscellaneous", "Miscellaneous", "custom_interest_total")
	+ _layer("custom_replacement", "Replacement", "custom_miscellaneous_total")
	+ _layer("custom_marketing_expenses", "Marketing Expenses", "custom_replacement_total")
	+ [
		dict(
			fieldname="custom_final_cost_section",
			label="Final Cost & MOQ Pricing",
			fieldtype="Section Break",
			insert_after="custom_marketing_expenses_total",
			depends_on='eval:doc.custom_bom_type=="Parent BOM"',
		),
		dict(
			fieldname="custom_bom_cost",
			label="BOM Cost",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			bold=1,
			insert_after="custom_final_cost_section",
		),
		dict(
			fieldname="custom_1k_moq_percentage",
			label="1K MOQ %",
			fieldtype="Percent",
			default="12",
			insert_after="custom_bom_cost",
			allow_on_submit=1,
		),
		dict(
			fieldname="custom_1k_moq_price",
			label="1K MOQ Price",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after="custom_1k_moq_percentage",
		),
		dict(
			fieldname="custom_3k_moq_percentage",
			label="3K MOQ %",
			fieldtype="Percent",
			default="10",
			insert_after="custom_1k_moq_price",
			allow_on_submit=1,
		),
		dict(
			fieldname="custom_3k_moq_price",
			label="3K MOQ Price",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after="custom_3k_moq_percentage",
		),
		dict(fieldname="custom_moq_col", fieldtype="Column Break", insert_after="custom_3k_moq_price"),
		dict(
			fieldname="custom_6k_moq_percentage",
			label="6K MOQ %",
			fieldtype="Percent",
			default="8",
			insert_after="custom_moq_col",
			allow_on_submit=1,
		),
		dict(
			fieldname="custom_6k_moq_price",
			label="6K MOQ Price",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after="custom_6k_moq_percentage",
		),
		dict(
			fieldname="custom_10k_moq_percentage",
			label="10K MOQ %",
			fieldtype="Percent",
			default="6",
			insert_after="custom_6k_moq_price",
			allow_on_submit=1,
		),
		dict(
			fieldname="custom_10k_moq_price",
			label="10K MOQ Price",
			fieldtype="Currency",
			read_only=1,
			precision="3",
			insert_after="custom_10k_moq_percentage",
		),
	]
)


QUOTATION_FIELDS = [
	# Read-only Data (not Link): traceability without a circular deletion dependency.
	dict(
		fieldname="lr_price_sheet",
		label="Price Sheet",
		fieldtype="Data",
		read_only=1,
		no_copy=1,
		insert_after="naming_series",
		in_standard_filter=1,
	),
]


def create_costing_fields():
	create_custom_fields(
		{
			"Item": ITEM_FIELDS,
			"BOM Item": BOM_ITEM_FIELDS,
			"BOM": BOM_FIELDS,
			"Quotation": QUOTATION_FIELDS,
		},
		update=True,
	)
