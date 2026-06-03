# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# "Listing of Documents" — the Focus 9 cross-stage worklist. One row per Sales
# Order showing how far it has travelled through the whole flow, so the team can
# spot what is stuck (e.g. PO raised but no GRN yet, or produced but not dispatched).

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns() -> list[dict]:
	return [
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Data", "width": 160},
		{"label": _("Item"), "fieldname": "item", "fieldtype": "Data", "width": 130},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 80},
		{"label": _("SO Status"), "fieldname": "so_status", "fieldtype": "Data", "width": 120},
		{"label": _("Planning"), "fieldname": "planning", "fieldtype": "Data", "width": 110},
		{"label": _("Indent"), "fieldname": "indent", "fieldtype": "Data", "width": 150},
		{"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Data", "width": 150},
		{"label": _("Inbound Stage"), "fieldname": "inbound", "fieldtype": "Data", "width": 120},
		{"label": _("Production"), "fieldname": "production", "fieldtype": "Data", "width": 120},
		{"label": _("Customer PDI"), "fieldname": "customer_pdi", "fieldtype": "Data", "width": 120},
		{"label": _("Dispatch"), "fieldname": "dispatch", "fieldtype": "Data", "width": 130},
	]


def _po_inbound_stage(po):
	"""Furthest inbound document reached for a Purchase Order."""
	if frappe.db.exists("Purchase Receipt Item", {"purchase_order": po, "docstatus": 1}):
		return "GRN"
	if frappe.db.exists("IQC", {"purchase_order": po, "docstatus": 1}):
		return "IQC"
	if frappe.db.exists("Inbound Logistics", {"purchase_order": po, "docstatus": 1}):
		return "Logistics"
	if frappe.db.exists("Vendor PDI", {"purchase_order": po, "docstatus": 1}):
		return "Vendor PDI"
	return "PO raised"


def get_data(filters) -> list[dict]:
	conds = {"docstatus": ["!=", 2]}
	if filters.get("company"):
		conds["company"] = filters["company"]
	if filters.get("customer"):
		conds["customer"] = filters["customer"]
	if filters.get("from_date") and filters.get("to_date"):
		conds["transaction_date"] = ["between", [filters["from_date"], filters["to_date"]]]

	rows = []
	for so in frappe.get_all("Sales Order", filters=conds,
							 fields=["name", "customer", "workflow_state", "status"],
							 order_by="transaction_date desc"):
		soi = frappe.get_all("Sales Order Item", {"parent": so.name},
							 ["item_code", "qty"], limit=1)
		item = soi[0].item_code if soi else ""
		qty = flt(soi[0].qty) if soi else 0

		# planning
		wos = frappe.get_all("Work Order", {"sales_order": so.name}, ["name", "status"])
		planning = wos[0].name and "Planned" if wos else "—"
		production = wos[0].status if wos else "—"

		# indent + PO (PO links the indent via the lr_indent_refs text field)
		indents = frappe.get_all("Indent", {"source_sales_order": so.name},
								 ["name", "workflow_state"])
		indent = ", ".join(f"{i.name} ({i.workflow_state})" for i in indents) or "—"
		po_set, inbound = [], "—"
		for i in indents:
			for po in frappe.get_all("Purchase Order",
									 {"lr_indent_refs": ["like", f"%{i.name}%"], "docstatus": ["!=", 2]},
									 pluck="name"):
				po_set.append(po)
		if po_set:
			stages = [_po_inbound_stage(po) for po in po_set]
			order = ["PO raised", "Vendor PDI", "Logistics", "IQC", "GRN"]
			inbound = min(stages, key=lambda s: order.index(s))  # the laggard
		purchase_order = ", ".join(sorted(set(po_set))) or "—"

		# customer PDI + dispatch
		cpdi = frappe.get_all("Customer PDI", {"sales_order": so.name, "docstatus": 1},
							  ["customer_signoff"], limit=1)
		customer_pdi = cpdi[0].customer_signoff if cpdi else "—"
		dn = frappe.get_all("Delivery Note Item", {"against_sales_order": so.name, "docstatus": 1},
							["parent"], limit=1)
		dispatch = dn[0].parent if dn else "—"

		rows.append({
			"sales_order": so.name, "customer": so.customer, "item": item, "qty": qty,
			"so_status": so.workflow_state or so.status, "planning": planning,
			"indent": indent, "purchase_order": purchase_order, "inbound": inbound,
			"production": production, "customer_pdi": customer_pdi, "dispatch": dispatch,
		})
	return rows
