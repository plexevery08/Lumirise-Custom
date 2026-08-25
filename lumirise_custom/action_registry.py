"""Version-controlled inventory and fail-closed contract for custom endpoints.

The registry is deliberately not whitelisted and does not dispatch methods. It
keeps every custom endpoint inventoried with its server contract. Seven reviewed
draft-producing mappers are approved for the guarded easy-use pilot; every
other action remains blocked until its own tests and rollback path are reviewed.
Existing ERPNext forms continue to call their hardened methods directly.
"""

from dataclasses import dataclass
from typing import Literal

import frappe
from frappe import _

from lumirise_custom.action_permissions import require_any_role, require_doctype_permissions
from lumirise_custom.feature_flags import require_enabled

EndpointKind = Literal["read", "action"]
ConfirmationLevel = Literal[
	"informational",
	"reversible_draft",
	"stock_quality_handoff",
	"financial_approval",
	"destructive",
]


@dataclass(frozen=True, slots=True)
class TargetPermission:
	doctype: str
	permissions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EndpointContract:
	method: str
	kind: EndpointKind
	action_id: str | None
	label: str
	source_doctype: str | None
	stage: str
	authorized_roles: tuple[str, ...]
	required_permission: str | None
	target_permissions: tuple[TargetPermission, ...]
	visible_condition: str
	enabled_condition: str
	missing_prerequisite_message: str
	preview_fields: tuple[str, ...]
	confirmation_level: ConfirmationLevel
	confirmation_template: str
	reason_required: bool
	effect_summary: str
	success_message: str
	next_owner: str
	reversal_route: str
	feature_flag: str | None
	approved_for_easy_ui: bool


SYSTEM = ("System Manager",)
ADMIN = ("Lumirise Operations", "System Manager")
SECURITY = ("Security User", "Logistics User", "Logistics Manager", "System Manager")
INWARD_MANAGERS = ("Logistics Manager", "System Manager")
PLANNING = ("Planning User", "Planning Manager", "System Manager")
PURCHASE = ("Purchase User", "Purchase Manager", "Purchase Head", "System Manager")
QUALITY = ("Quality User", "Quality Inspector", "Quality Manager", "System Manager")
LOGISTICS = ("Logistics User", "Logistics Manager", "System Manager")
STORES = ("Factory Store Manager", "Stock User", "Stock Manager", "System Manager")
PRODUCTION = ("Line Supervisor", "Manufacturing User", "Manufacturing Manager", "System Manager")
SALES = ("Sales User", "Sales Coordinator", "Sales Manager", "System Manager")
ACCOUNTS = ("Accounts User", "Accounts Manager", "System Manager")
PRICING = ("Pricing Manager", "Sales Approver", "MD", "System Manager")
ENGINEERING = ("BOM/Engineering User", "Manufacturing Manager", "MD", "System Manager")

# Only draft-producing mappers are approved for the first post-read-only pilot.
# They return an unsaved document and do not post stock, submit workflows, or
# change accounting state. Every other action remains inventoried and blocked.
EASY_UI_APPROVED_ACTIONS = frozenset(
	{
		"inbound.create_vendor_pdi",
		"inbound.create_logistics",
		"inbound.create_iqc",
		"inbound.create_grn",
		"dispatch.create_customer_pdi",
		"dispatch.create_delivery_note",
		"finance.create_sales_invoice",
	}
)


def _target(doctype: str, *permissions: str) -> TargetPermission:
	return TargetPermission(doctype=doctype, permissions=tuple(permissions))


def _read(method: str, source_doctype: str | None) -> EndpointContract:
	return EndpointContract(
		method=method,
		kind="read",
		action_id=None,
		label=method.rsplit(".", 1)[-1].replace("_", " ").title(),
		source_doctype=source_doctype,
		stage="read",
		authorized_roles=(),
		required_permission="read" if source_doctype else None,
		target_permissions=(),
		visible_condition="The caller can read the authoritative source data.",
		enabled_condition="The requested source and filters are valid.",
		missing_prerequisite_message="The source record is unavailable or not permitted.",
		preview_fields=(),
		confirmation_level="informational",
		confirmation_template="",
		reason_required=False,
		effect_summary="Read-only; creates no document and posts no ledger entry.",
		success_message="Authoritative data returned.",
		next_owner="",
		reversal_route="No reversal is required for a read.",
		feature_flag=None,
		approved_for_easy_ui=True,
	)


def _action(
	action_id: str,
	method: str,
	source_doctype: str | None,
	roles: tuple[str, ...],
	*,
	stage: str,
	targets: tuple[TargetPermission, ...] = (),
	permission: str = "write",
	level: ConfirmationLevel = "reversible_draft",
	reason_required: bool = False,
	effect: str,
	reversal: str,
	next_owner: str = "Resolved from the resulting source document state.",
	preview_fields: tuple[str, ...] = ("name", "workflow_state", "modified"),
) -> EndpointContract:
	label = action_id.rsplit(".", 1)[-1].replace("_", " ").title()
	return EndpointContract(
		method=method,
		kind="action",
		action_id=action_id,
		label=label,
		source_doctype=source_doctype,
		stage=stage,
		authorized_roles=roles,
		required_permission=permission if source_doctype else None,
		target_permissions=targets,
		visible_condition="The source is in an allowed state and the actor has the named business role.",
		enabled_condition="Server role, record, state, quantity, duplicate, and downstream permission checks pass.",
		missing_prerequisite_message="Open the source document to resolve its state, quantity, or permission prerequisite.",
		preview_fields=preview_fields,
		confirmation_level=level,
		confirmation_template=f"Review the source and consequences before {label.lower()}.",
		reason_required=reason_required,
		effect_summary=effect,
		success_message=f"{label} completed; open the returned source or downstream document for details.",
		next_owner=next_owner,
		reversal_route=reversal,
		feature_flag="easy_ui_state_actions",
		approved_for_easy_ui=action_id in EASY_UI_APPROVED_ACTIONS,
	)


READ_ENDPOINTS = tuple(
	_read(method, source)
	for method, source in (
		("lumirise_custom.defaults.form_warehouse_defaults", "Lumirise Operations Settings"),
		(
			"lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.fetch_sales_order_items",
			"Customer PDI",
		),
		("lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.fg_on_hand", "Customer PDI"),
		("lumirise_custom.lumirise_custom.doctype.indent.indent.warehouse_balance", "Indent"),
		("lumirise_custom.lumirise_custom.doctype.indent.indent.get_consolidated_po_items", "Indent"),
		("lumirise_custom.lumirise_custom.doctype.indent.indent.get_indent_items", "Indent"),
		(
			"lumirise_custom.lumirise_custom.doctype.lumirise_production_schedule."
			"lumirise_production_schedule.get_suggested_order",
			"Sales Order",
		),
		("lumirise_custom.lumirise_custom.doctype.price_sheet.price_sheet.get_finish_options", "Price Sheet"),
		(
			"lumirise_custom.lumirise_custom.doctype.purchase_plan.purchase_plan.get_indent_qty",
			"Purchase Plan",
		),
		(
			"lumirise_custom.lumirise_custom.doctype.purchase_plan.purchase_plan.get_rm_rate",
			"Purchase Plan",
		),
		("lumirise_custom.lumirise_custom.doctype.purchase_plan.purchase_plan.get_kit_bom", "Purchase Plan"),
		("lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.scan_package", "RM Package"),
		(
			"lumirise_custom.lumirise_custom.doctype.rm_price_book.rm_price_book.get_rm_price_template",
			"RM Price Book",
		),
		("lumirise_custom.mr_insights.mr_item_snapshot", "Material Request"),
		("lumirise_custom.production.shop_floor_available_qty", "Work Order"),
		("lumirise_custom.production.line_transfer_breakdown", "Work Order"),
		("lumirise_custom.production.get_production_lines", "Warehouse"),
		("lumirise_custom.purchase_reco.get_bom_reconciliation", "Purchase Order"),
		(
			"lumirise_custom.lumirise_custom.doctype.stock_reconciliation.stock_reconciliation.get_stock_reconciliation_template",
			"Stock Reconciliation",
		),
		("lumirise_custom.quality.aql_for_lot", None),
		("lumirise_custom.queries.master_box_finish_query", "Box Finish"),
		("lumirise_custom.queries.mono_box_finish_query", "Mono Box Finish"),
		("lumirise_custom.queries.line_warehouse_query", "Warehouse"),
		("lumirise_custom.dropship.get_open_subcontracting_orders", "Supplier"),
		("lumirise_custom.dropship.get_sco_bom_summary", "Subcontracting Order"),
	)
)


ACTION_ENDPOINTS = (
	_action(
		"inbound.create_vendor_pdi",
		"lumirise_custom.chain.make_vendor_pdi",
		"Purchase Order",
		PURCHASE,
		stage="vendor_pdi",
		permission="read",
		targets=(_target("Vendor PDI", "create"),),
		effect="Creates an unsaved Vendor PDI draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"inbound.create_logistics",
		"lumirise_custom.chain.make_inbound_logistics",
		"Vendor PDI",
		LOGISTICS,
		stage="transit",
		permission="read",
		targets=(_target("Inbound Logistics", "create"),),
		effect="Creates an unsaved Inbound Logistics draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"inbound.create_iqc",
		"lumirise_custom.chain.make_iqc",
		"Inbound Logistics",
		QUALITY,
		stage="iqc",
		permission="read",
		targets=(_target("IQC", "create"),),
		effect="Creates an unsaved IQC draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"inbound.create_grn",
		"lumirise_custom.chain.make_grn",
		"IQC",
		PURCHASE + STORES,
		stage="grn",
		permission="read",
		targets=(_target("Purchase Receipt", "create"),),
		effect="Creates an unsaved Purchase Receipt draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"dispatch.create_customer_pdi",
		"lumirise_custom.chain.make_customer_pdi",
		"Sales Order",
		SALES + QUALITY,
		stage="customer_pdi",
		permission="read",
		targets=(_target("Customer PDI", "create"),),
		effect="Creates an unsaved Customer PDI draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"dispatch.create_delivery_note",
		"lumirise_custom.chain.make_delivery_note",
		"Sales Order",
		SALES + STORES,
		stage="dispatch",
		permission="read",
		targets=(_target("Delivery Note", "create"),),
		effect="Creates an unsaved Delivery Note draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"finance.create_sales_invoice",
		"lumirise_custom.chain.make_sales_invoice",
		"Delivery Note",
		ACCOUNTS,
		stage="invoice",
		permission="read",
		targets=(_target("Sales Invoice", "create"),),
		effect="Creates an unsaved Sales Invoice draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"dispatch.approve_packing",
		"lumirise_custom.events.approve_packing",
		"Packing Record",
		STORES,
		stage="packing",
		level="stock_quality_handoff",
		effect="Records packing approval on the source document.",
		reversal="Use the source document's versioned correction process.",
	),
	_action(
		"admin.run_health_check",
		"lumirise_custom.health_check.trigger_health_check",
		None,
		ADMIN,
		stage="administration",
		targets=(_target("Health Check Run", "create"),),
		effect="Runs diagnostics and records a Health Check Run.",
		reversal="No business transaction is posted; retain the diagnostic record.",
	),
	_action(
		"engineering.approve_change",
		"lumirise_custom.lumirise_custom.doctype.bom_change_request.bom_change_request.approve_change",
		"BOM Change Request",
		ENGINEERING,
		stage="change_approval",
		level="financial_approval",
		effect="Records engineering approval.",
		reversal="Reject or supersede through the BOM Change Request workflow.",
	),
	_action(
		"engineering.approve_cost",
		"lumirise_custom.lumirise_custom.doctype.bom_change_request.bom_change_request.approve_cost",
		"BOM Change Request",
		ENGINEERING,
		stage="cost_approval",
		targets=(_target("BOM", "create", "submit"), _target("Item", "write")),
		level="financial_approval",
		effect="Creates and submits a new BOM version and updates the Item default.",
		reversal="Create a reviewed replacement BOM version; do not delete submitted BOM history.",
	),
	_action(
		"engineering.reject_change",
		"lumirise_custom.lumirise_custom.doctype.bom_change_request.bom_change_request.reject",
		"BOM Change Request",
		ENGINEERING,
		stage="change_approval",
		level="financial_approval",
		reason_required=True,
		effect="Rejects the BOM change request with an audit comment.",
		reversal="Reopen through a new or explicitly reset request.",
	),
	_action(
		"customer_pdi.request_send",
		"lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.send_for_authorization",
		"Customer PDI",
		STORES,
		stage="customer_pdi",
		level="stock_quality_handoff",
		effect="Requests authorization for a stock movement.",
		reversal="Reject the pending request before stock is moved.",
	),
	_action(
		"customer_pdi.authorize_send",
		"lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.authorize_send",
		"Customer PDI",
		STORES,
		stage="customer_pdi",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		effect="Authorizes and posts the PDI stock transfer.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"customer_pdi.reject_send",
		"lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.reject_send",
		"Customer PDI",
		STORES,
		stage="customer_pdi",
		level="stock_quality_handoff",
		reason_required=True,
		effect="Rejects a pending send request.",
		reversal="Submit a new authorization request after correction.",
	),
	_action(
		"customer_pdi.complete_inspection",
		"lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.complete_inspection",
		"Customer PDI",
		QUALITY,
		stage="customer_pdi",
		level="stock_quality_handoff",
		reason_required=True,
		effect="Records the final inspection result and quality handoff.",
		reversal="Use the controlled reopen action and retain the previous audit trail.",
	),
	_action(
		"customer_pdi.authorize_return",
		"lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.authorize_return",
		"Customer PDI",
		STORES,
		stage="customer_pdi",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		reason_required=True,
		effect="Posts the authorized return stock movement.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"customer_pdi.reopen",
		"lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.reopen_as_draft",
		"Customer PDI",
		QUALITY,
		stage="customer_pdi",
		level="destructive",
		reason_required=True,
		effect="Reopens a completed inspection as a draft.",
		reversal="Re-complete the inspection with corrected evidence.",
	),
	_action(
		"inbound.mark_in_transit",
		"lumirise_custom.lumirise_custom.doctype.inbound_logistics.inbound_logistics.mark_in_transit",
		"Inbound Logistics",
		LOGISTICS,
		stage="transit",
		effect="Advances the consignment to In Transit.",
		reversal="Correct the source status through the controlled logistics workflow.",
	),
	_action(
		"inbound.approve_gate",
		"lumirise_custom.lumirise_custom.doctype.inbound_logistics.inbound_logistics.approve_gate",
		"Inbound Logistics",
		LOGISTICS,
		stage="gate",
		effect="Records gate approval.",
		reversal="Use the controlled logistics correction route and retain the audit trail.",
	),
	_action(
		"inbound.verify_documents",
		"lumirise_custom.lumirise_custom.doctype.inbound_logistics.inbound_logistics.verify_documents",
		"Inbound Logistics",
		LOGISTICS,
		stage="gate",
		effect="Records document verification.",
		reversal="Correct the verification on the source record with an audit note.",
	),
	_action(
		"inbound.mark_reached",
		"lumirise_custom.lumirise_custom.doctype.inbound_logistics.inbound_logistics.mark_reached",
		"Inbound Logistics",
		LOGISTICS,
		stage="arrival",
		effect="Advances the consignment to Reached Warehouse.",
		reversal="Use the controlled logistics correction route and retain the audit trail.",
	),
	_action(
		"inbound.release_container",
		"lumirise_custom.lumirise_custom.doctype.inbound_logistics.inbound_logistics.release_container",
		"Inbound Logistics",
		PURCHASE,
		stage="release",
		level="financial_approval",
		effect="Records commercial release of the inbound container.",
		reversal="Correct through the source workflow; preserve the release history.",
	),
	_action(
		"planning.create_purchase_plan",
		"lumirise_custom.lumirise_custom.doctype.indent.indent.make_purchase_plan",
		"Indent",
		PLANNING + PURCHASE,
		stage="purchase_planning",
		targets=(_target("Purchase Plan", "create"),),
		effect="Creates a Purchase Plan draft from approved Indents.",
		reversal="Cancel or delete the draft before downstream orders are created.",
	),
	_action(
		"quality.start_iqc",
		"lumirise_custom.lumirise_custom.doctype.iqc.iqc.start_testing",
		"IQC",
		QUALITY,
		stage="iqc",
		level="stock_quality_handoff",
		effect="Moves IQC into testing.",
		reversal="Place the IQC on hold or use its controlled correction path.",
	),
	_action(
		"quality.record_iqc_result",
		"lumirise_custom.lumirise_custom.doctype.iqc.iqc.record_result",
		"IQC",
		QUALITY,
		stage="iqc",
		level="stock_quality_handoff",
		reason_required=True,
		effect="Records accepted and rejected inspection quantities.",
		reversal="Use the controlled IQC correction and stock-document reversal path.",
	),
	_action(
		"quality.hold_iqc",
		"lumirise_custom.lumirise_custom.doctype.iqc.iqc.hold",
		"IQC",
		QUALITY,
		stage="iqc",
		level="stock_quality_handoff",
		reason_required=True,
		effect="Places IQC on hold with a reason.",
		reversal="Resume testing through the source document after resolving the hold.",
	),
	_action(
		"production.refresh_job_output",
		"lumirise_custom.lumirise_custom.doctype.lumirise_job_card.lumirise_job_card.fetch_produced_from_wo",
		"Lumirise Job Card",
		PRODUCTION,
		stage="production",
		effect="Refreshes produced quantity from the authoritative Work Order.",
		reversal="Refresh again from the authoritative Work Order.",
	),
	_action(
		"planning.fetch_schedule_orders",
		"lumirise_custom.lumirise_custom.doctype.lumirise_production_schedule.lumirise_production_schedule.fetch_sales_orders",
		"Lumirise Production Schedule",
		PLANNING,
		stage="scheduling",
		effect="Updates a draft schedule from readable Sales Orders.",
		reversal="Remove or refetch draft schedule rows before submission.",
	),
	_action(
		"planning.release_schedule_day",
		"lumirise_custom.lumirise_custom.doctype.lumirise_production_schedule.lumirise_production_schedule.release_day",
		"Lumirise Production Schedule",
		PLANNING + PRODUCTION,
		stage="scheduling",
		targets=(_target("Lumirise Job Card", "create"),),
		effect="Creates deduplicated Job Cards for the released day.",
		reversal="Cancel or close unstarted Job Cards through their source workflow.",
	),
	_action(
		"planning.roll_backlog",
		"lumirise_custom.lumirise_custom.doctype.lumirise_production_schedule.lumirise_production_schedule.roll_backlog",
		"Lumirise Production Schedule",
		PLANNING + PRODUCTION,
		stage="scheduling",
		targets=(_target("Lumirise Job Card", "create"),),
		effect="Creates deduplicated backlog Job Cards.",
		reversal="Cancel or close unstarted backlog Job Cards through their source workflow.",
	),
	_action(
		"planning.compute_material_plan",
		"lumirise_custom.lumirise_custom.doctype.material_planning.material_planning.compute_plan",
		"Material Planning",
		PLANNING,
		stage="material_planning",
		effect="Recomputes draft plan lines from authoritative quantity sources.",
		reversal="Recompute again or discard unsaved draft changes.",
	),
	_action(
		"production.create_material_receipt",
		"lumirise_custom.lumirise_custom.doctype.material_receipt.material_receipt.make_material_receipt",
		"Work Order",
		PRODUCTION,
		stage="material_handoff",
		targets=(_target("Material Receipt", "create"),),
		effect="Creates an unsaved Material Receipt draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"pricing.populate_approvals",
		"lumirise_custom.lumirise_custom.doctype.price_sheet.price_sheet.populate_approval_items",
		"Price Sheet",
		PRICING,
		stage="pricing",
		effect="Refreshes approval rows on a draft Price Sheet.",
		reversal="Recompute or discard draft changes.",
	),
	_action(
		"pricing.preview",
		"lumirise_custom.lumirise_custom.doctype.price_sheet.price_sheet.preview_prices",
		"Price Sheet",
		PRICING,
		stage="pricing",
		effect="Calculates and stores draft price previews.",
		reversal="Recompute or discard draft changes.",
	),
	_action(
		"pricing.approve",
		"lumirise_custom.lumirise_custom.doctype.price_sheet.price_sheet.approve",
		"Price Sheet",
		PRICING,
		stage="pricing",
		targets=(_target("Quotation", "create"),),
		level="financial_approval",
		effect="Records approval and may create the authorized quotation draft.",
		reversal="Use a replacement Price Sheet/Quotation and preserve approval history.",
	),
	_action(
		"pricing.reject",
		"lumirise_custom.lumirise_custom.doctype.price_sheet.price_sheet.reject",
		"Price Sheet",
		PRICING,
		stage="pricing",
		level="financial_approval",
		reason_required=True,
		effect="Rejects the Price Sheet with a required reason.",
		reversal="Correct and resubmit through the pricing workflow.",
	),
	_action(
		"purchase.create_orders",
		"lumirise_custom.lumirise_custom.doctype.purchase_plan.purchase_plan.create_purchase_orders",
		"Purchase Plan",
		PURCHASE,
		stage="purchase_order",
		targets=(_target("Purchase Order", "create"),),
		level="financial_approval",
		effect="Creates deduplicated Purchase Order drafts from the plan.",
		reversal="Cancel/delete drafts before release or use native PO cancellation afterward.",
	),
	_action(
		"stock.create_package",
		"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.create_from_inbound",
		"Inbound Logistics",
		STORES,
		stage="package_identity",
		targets=(_target("RM Package", "create"), _target("Batch", "create")),
		level="stock_quality_handoff",
		effect="Creates Batch and RM Package identity records without posting stock.",
		reversal="Delete unused draft identities only when no ledger/document links exist.",
	),
	_action(
		"stock.release_package",
		"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.release_after_grn",
		"RM Package",
		STORES + QUALITY,
		stage="package_release",
		level="stock_quality_handoff",
		effect="Links the submitted GRN/IQC and marks the package available.",
		reversal="Correct the package through the source GRN/IQC reversal path.",
	),
	_action(
		"stock.put_away_package",
		"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.put_away",
		"RM Package",
		STORES,
		stage="put_away",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		effect="Posts a native Material Transfer and updates package location.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"pricing.import_rm_prices",
		"lumirise_custom.lumirise_custom.doctype.rm_price_book.rm_price_book.import_rows",
		"RM Price Book",
		PURCHASE,
		stage="rm_pricing",
		level="financial_approval",
		effect="Imports rows into a draft RM Price Book.",
		reversal="Correct/reimport the draft before approval.",
	),
	_action(
		"quality.start_vendor_pdi",
		"lumirise_custom.lumirise_custom.doctype.vendor_pdi.vendor_pdi.start_inspection",
		"Vendor PDI",
		QUALITY,
		stage="vendor_pdi",
		level="stock_quality_handoff",
		effect="Moves Vendor PDI into inspection.",
		reversal="Place the PDI on hold or use its controlled correction path.",
	),
	_action(
		"quality.record_vendor_pdi",
		"lumirise_custom.lumirise_custom.doctype.vendor_pdi.vendor_pdi.record_result",
		"Vendor PDI",
		QUALITY,
		stage="vendor_pdi",
		level="stock_quality_handoff",
		reason_required=True,
		effect="Records Vendor PDI quantities and result.",
		reversal="Use the controlled Vendor PDI correction path.",
	),
	_action(
		"quality.dispatch_vendor_pdi",
		"lumirise_custom.lumirise_custom.doctype.vendor_pdi.vendor_pdi.dispatch",
		"Vendor PDI",
		QUALITY,
		stage="vendor_pdi",
		level="stock_quality_handoff",
		effect="Records dispatch after Vendor PDI.",
		reversal="Correct through the source document before downstream receipt.",
	),
	_action(
		"quality.hold_vendor_pdi",
		"lumirise_custom.lumirise_custom.doctype.vendor_pdi.vendor_pdi.hold",
		"Vendor PDI",
		QUALITY,
		stage="vendor_pdi",
		level="stock_quality_handoff",
		reason_required=True,
		effect="Places Vendor PDI on hold with a reason.",
		reversal="Resume through the source document after resolving the hold.",
	),
	_action(
		"production.issue_shop_floor",
		"lumirise_custom.production.issue_to_shop_floor",
		"Work Order",
		PRODUCTION,
		stage="material_issue",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		effect="Posts the native material issue/transfer for the Work Order.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"production.transfer_line",
		"lumirise_custom.production.transfer_to_line",
		"Work Order",
		PRODUCTION,
		stage="line_transfer",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		effect="Posts material transfer to the selected production line.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"production.receive_fg",
		"lumirise_custom.production.receive_finished_goods",
		"Work Order",
		PRODUCTION,
		stage="fg_receipt",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		effect="Posts finished-goods receipt against the Work Order.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"production.reject_output",
		"lumirise_custom.production.reject_from_line",
		"Work Order",
		PRODUCTION + QUALITY,
		stage="production_rejection",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		reason_required=True,
		effect="Posts rejected output to the configured rejection warehouse.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"production.move_dispatch",
		"lumirise_custom.production.move_to_dispatch",
		"Work Order",
		PRODUCTION + STORES,
		stage="dispatch_handoff",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		effect="Posts finished-goods transfer to Dispatch FG.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"quality.apply_sampling_plan",
		"lumirise_custom.quality.apply_to_iqc",
		"IQC",
		QUALITY,
		stage="iqc",
		level="stock_quality_handoff",
		effect="Stores the calculated sampling plan on IQC.",
		reversal="Recalculate from the authoritative lot and AQL settings.",
	),
	_action(
		"quality.issue_sample",
		"lumirise_custom.samples.issue_sample",
		"IQC",
		QUALITY,
		stage="sample_custody",
		level="stock_quality_handoff",
		reason_required=True,
		effect="Records sample custody without posting pre-GRN stock.",
		reversal="Return/disposition the sample through the controlled sample action.",
	),
	_action(
		"quality.return_sample",
		"lumirise_custom.samples.return_sample",
		"IQC",
		QUALITY,
		stage="sample_custody",
		targets=(_target("Stock Entry", "create", "submit"),),
		level="stock_quality_handoff",
		reason_required=True,
		effect="Records sample disposition and posts stock when applicable.",
		reversal="Cancel or reverse the Stock Entry through native ERPNext controls.",
	),
	_action(
		"purchase.create_service_order",
		"lumirise_custom.service_order.make_service_order",
		"Indent",
		PURCHASE,
		stage="subcontract_order",
		targets=(_target("Purchase Order", "create"), _target("Item", "create")),
		level="financial_approval",
		effect="Creates a draft subcontract Purchase Order.",
		reversal="Cancel/delete the draft before release or use native PO cancellation afterward.",
	),
	_action(
		"stock.create_work_order_pick",
		"lumirise_custom.stores.make_work_order_pick_list",
		"Work Order",
		STORES + PRODUCTION,
		stage="picking",
		targets=(_target("Pick List", "create"),),
		effect="Creates an unsaved Work Order Pick List draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"stock.create_delivery_pick",
		"lumirise_custom.stores.make_delivery_pick_list",
		"Sales Order",
		STORES + SALES,
		stage="picking",
		targets=(_target("Pick List", "create"),),
		effect="Creates an unsaved Delivery Pick List draft.",
		reversal="Discard the unsaved draft.",
	),
	_action(
		"inward.register_vehicle_arrival",
		"lumirise_custom.inward_process.register_vehicle_arrival",
		"Inbound Logistics",
		SECURITY,
		stage="gate",
		effect="Registers vehicle arrival and creates the manager gate-approval task.",
		reversal="Correct the inbound record through the controlled logistics workflow.",
	),
	_action(
		"inward.approve_vehicle_entry",
		"lumirise_custom.inward_process.approve_vehicle_entry",
		"Inbound Logistics",
		INWARD_MANAGERS,
		stage="gate",
		effect="Approves the vehicle entry after security registration.",
		reversal="Reject and recreate the inbound record when the vehicle must not enter.",
	),
	_action(
		"inward.reject_vehicle_entry",
		"lumirise_custom.inward_process.reject_vehicle_entry",
		"Inbound Logistics",
		INWARD_MANAGERS,
		stage="gate",
		reason_required=True,
		effect="Rejects vehicle entry with a required reason.",
		reversal="Create a new inbound record after the rejection is resolved.",
	),
	_action(
		"inward.verify_gate_entry",
		"lumirise_custom.inward_process.verify_gate_entry",
		"Inbound Logistics",
		SECURITY,
		stage="gate",
		effect="Records the security gate stamp after manager approval.",
		reversal="Correct the gate evidence through the controlled logistics workflow.",
	),
	_action(
		"inward.verify_documents",
		"lumirise_custom.inward_process.verify_documents",
		"Inbound Logistics",
		LOGISTICS,
		stage="document_gate",
		effect="Records the mandatory invoice, packing-list, waybill, and handover checks.",
		reversal="Correct the document exception with an audit trail.",
	),
	_action(
		"inward.raise_iqc_task",
		"lumirise_custom.inward_process.raise_iqc_task",
		"Inbound Logistics",
		INWARD_MANAGERS,
		stage="iqc",
		targets=(_target("IQC", "create"),),
		effect="Creates the IQC record and mandatory quality task after document verification.",
		reversal="Resolve or cancel the generated IQC through its controlled workflow.",
	),
	_action(
		"inward.start_unloading",
		"lumirise_custom.inward_process.start_unloading",
		"Inbound Logistics",
		LOGISTICS,
		stage="unloading",
		effect="Starts unloading only after gate, document, and IQC prerequisites pass.",
		reversal="Complete or correct the unloading checkpoint on the inbound record.",
	),
	_action(
		"inward.complete_unloading",
		"lumirise_custom.inward_process.complete_unloading",
		"Inbound Logistics",
		LOGISTICS,
		stage="unloading",
		effect="Closes the unloading checkpoint and opens physical verification.",
		reversal="Correct the inbound record before final sign-off.",
	),
	_action(
		"inward.record_physical_verification",
		"lumirise_custom.inward_process.record_physical_verification",
		"Inbound Logistics",
		LOGISTICS,
		stage="physical_verification",
		reason_required=True,
		effect="Records physical quantity/damage verification and creates exception tasks when needed.",
		reversal="Resolve the exception with evidence and a documented reference.",
	),
	_action(
		"inward.verify_invoice_price",
		"lumirise_custom.inward_process.verify_invoice_price",
		"Inbound Logistics",
		INWARD_MANAGERS,
		stage="commercial_verification",
		effect="Records manager verification of invoice price against the Purchase Order.",
		reversal="Correct the commercial verification through the inbound record.",
	),
	_action(
		"inward.resolve_exception",
		"lumirise_custom.inward_process.resolve_exception",
		"Inbound Process Exception",
		PURCHASE,
		stage="exception_resolution",
		reason_required=True,
		effect="Resolves a quantity or damage exception with a debit note, claim, replacement, or ERP reference.",
		reversal="Reopen through a new exception record with the original evidence retained.",
	),
	_action(
		"inward.authorize_storage",
		"lumirise_custom.inward_process.authorize_storage",
		"Inbound Logistics",
		INWARD_MANAGERS,
		stage="storage_authorization",
		effect="Authorizes the allocated leaf rack after IQC, physical, price, and exception checks pass.",
		reversal="Correct the storage authorization through the controlled inbound workflow.",
	),
	_action(
		"inward.accept_at_rm_store",
		"lumirise_custom.inward_process.accept_at_rm_store",
		"Inbound Logistics",
		STORES,
		stage="store_acceptance",
		effect="Records RM Stores physical acceptance with the signed packing list.",
		reversal="Correct the acceptance through the controlled store workflow.",
	),
	_action(
		"inward.verify_putaway_and_erp",
		"lumirise_custom.inward_process.verify_putaway_and_erp",
		"Inbound Logistics",
		STORES,
		stage="put_away",
		effect="Verifies package coverage, barcode put-away, and the rack stock-note reference.",
		reversal="Correct the put-away through native stock controls and retain the evidence.",
	),
	_action(
		"inward.handover_documents",
		"lumirise_custom.inward_process.handover_documents",
		"Inbound Logistics",
		LOGISTICS,
		stage="document_handover",
		effect="Records handover of the GRN, invoice, waybill, IQC report, and supporting bundle.",
		reversal="Attach a corrected bundle through the inbound workflow.",
	),
	_action(
		"inward.close_inward",
		"lumirise_custom.inward_process.close_inward",
		"Inbound Logistics",
		INWARD_MANAGERS,
		stage="close",
		effect="Performs final inward sign-off after ERP, store, handover, and exception checks pass.",
		reversal="Reopen through a controlled correction record while retaining sign-off history.",
	),
	_action(
		"dropship.receive_and_forward",
		"lumirise_custom.dropship.receive_and_forward",
		"Purchase Order",
		STORES + PURCHASE,
		stage="drop_ship",
		targets=(_target("Purchase Receipt", "create", "submit"), _target("Stock Entry", "create")),
		level="stock_quality_handoff",
		effect="Posts the supplier receipt and prepares the consignee transfer as a draft.",
		reversal="Cancel the native receipt or discard the unsubmitted transfer draft.",
	),
	_action(
		"stock.confirm_package_label",
		"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.confirm_label_applied",
		"RM Package",
		STORES,
		stage="package_identity",
		effect="Records the post-GRN physical confirmation that the printed LPN is applied.",
		reversal="Correct the package evidence through the controlled warehouse process.",
	),
)


ENDPOINT_INVENTORY = {contract.method: contract for contract in (*READ_ENDPOINTS, *ACTION_ENDPOINTS)}
ACTION_REGISTRY = {contract.action_id: contract for contract in ACTION_ENDPOINTS if contract.action_id}

if len(ENDPOINT_INVENTORY) != len(READ_ENDPOINTS) + len(ACTION_ENDPOINTS):
	raise RuntimeError("Duplicate endpoint method in Phase 0 inventory")
if len(ACTION_REGISTRY) != len(ACTION_ENDPOINTS):
	raise RuntimeError("Duplicate stable action ID in Phase 0 registry")


def get_action(action_id: str) -> EndpointContract:
	try:
		return ACTION_REGISTRY[action_id]
	except KeyError:
		frappe.throw(_("Unknown Lumirise action contract: {0}").format(action_id), frappe.ValidationError)


def require_easy_ui_action(action_id: str, docname: str | None = None) -> EndpointContract:
	"""Authorize one of the reviewed registry-driven pilot actions."""
	contract = get_action(action_id)
	if not contract.approved_for_easy_ui:
		frappe.throw(
			_("This action is inventoried but not approved for easy-use UI."), frappe.PermissionError
		)
	require_enabled(contract.feature_flag or "easy_ui_state_actions")
	require_any_role(frozenset(contract.authorized_roles), "Your role cannot perform this action.")
	if contract.source_doctype and contract.required_permission:
		frappe.has_permission(
			contract.source_doctype,
			contract.required_permission,
			docname,
			throw=True,
		)
	for target in contract.target_permissions:
		require_doctype_permissions(target.doctype, *target.permissions)
	return contract
