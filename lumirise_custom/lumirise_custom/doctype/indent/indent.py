# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Indent = the Focus 9 rate-less purchase request that sits between Planning and
# the Purchase Order. Multiple approved Indents merge into ONE Purchase Order
# (common parts like screws summed across orders). The buyer chooses the supplier
# and rates on the PO screen -- we never pre-set a supplier or split the demand by
# supplier. A BOM-reconciliation check flags any model component missing from the
# consolidated demand.

import json

import frappe
from frappe.model.document import Document
from frappe.utils import flt, nowdate, add_days

COMPANY = "Lumirise"
RM_STORE = "Stores - L"


class Indent(Document):
	def validate(self):
		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(f"Row {row.idx}: Qty must be greater than zero.")


@frappe.whitelist()
def get_consolidated_po_items(indents):
	"""Aggregate the items across the selected Indents into ONE Purchase Order's
	worth of lines (common parts summed, accurate qty). Does NOT create a PO and
	does NOT set a supplier -- the client opens a fresh Purchase Order form with
	these items and fills in supplier/rates there.
	Returns {items, indents, reconciliation}."""
	frappe.has_permission("Purchase Order", "create", throw=True)
	if isinstance(indents, str):
		indents = json.loads(indents)
	if not indents:
		frappe.throw("Select at least one Indent.")

	# aggregate qty by (item, uom) across all selected indents, first-seen order
	agg = {}
	order = []
	models = set()
	for name in indents:
		ind = frappe.get_doc("Indent", name)
		for row in ind.items:
			if row.model:
				models.add(row.model)
			uom = row.uom or "Nos"
			key = (row.item_code, uom)
			if key not in agg:
				agg[key] = 0.0
				order.append(key)
			agg[key] += flt(row.qty)

	ordered_items = {item_code for (item_code, _uom) in order}

	# Pre-fetch item_name / description for the lines. Building the PO rows
	# programmatically on the client does NOT fire ERPNext's auto-fetch from
	# item_code, so item_name (a mandatory PO Item field) would stay blank.
	item_meta = {
		r.name: r for r in frappe.get_all(
			"Item",
			filters={"name": ["in", list(ordered_items)]},
			fields=["name", "item_name", "description", "stock_uom"],
		)
	} if ordered_items else {}

	items = []
	for (item_code, uom) in order:
		meta = item_meta.get(item_code)
		items.append({
			"item_code": item_code,
			"item_name": (meta.item_name if meta else None) or item_code,
			"description": (meta.description if meta else None) or item_code,
			"qty": agg[(item_code, uom)],
			"uom": uom,
			"stock_uom": (meta.stock_uom if meta else uom) or uom,
			"conversion_factor": 1,
			"schedule_date": add_days(nowdate(), 15),
			"warehouse": RM_STORE,
		})

	warnings = _reconcile_against_bom(models, ordered_items)
	return {"items": items, "indents": list(indents), "reconciliation": warnings}


def _reconcile_against_bom(models, ordered_items):
	"""Flag any component in a model's BOM that is NOT present in the
	consolidated PO demand -- the client's 1-2 hr manual screw-reconciliation,
	automated. `ordered_items` is the set of item codes going onto the PO."""
	warnings = []
	for model in models:
		bom = frappe.db.get_value("Item", model, "default_bom")
		if not bom:
			continue
		bom_items = frappe.get_all("BOM Item", {"parent": bom}, pluck="item_code")
		# a genuine gap = a BOM component NOT on the consolidated PO AND with no
		# stock to cover it (the part the planner forgot to indent).
		missing = [
			i for i in bom_items
			if i not in ordered_items
			and flt(frappe.db.get_value("Bin", {"item_code": i, "warehouse": RM_STORE}, "actual_qty")) <= 0
		]
		if missing:
			warnings.append({"model": model, "missing_from_indent": missing})
	return warnings


def _default_supplier(item_code):
	"""Best-guess vendor for an item: its Item Default default_supplier (first found).
	The buyer can override it per line on the Purchase Plan."""
	return frappe.db.get_value("Item Default", {"parent": item_code}, "default_supplier")


@frappe.whitelist()
def make_purchase_plan(indents):
	"""Ajay review 2026-06-14: merge the selected Indents into ONE Purchase Plan
	(qty summed per item, source indents tracked per line) with a per-line vendor
	column, so the buyer assigns a vendor to each item and then splits the demand
	into one Purchase Order per vendor. Creates a Draft Purchase Plan and returns
	its name. Replaces the old straight-to-one-PO path."""
	frappe.has_permission("Purchase Plan", "create", throw=True)
	if isinstance(indents, str):
		indents = json.loads(indents)
	if not indents:
		frappe.throw("Select at least one Indent.")

	# aggregate qty by (item, uom); remember which indents fed each line + model.
	agg = {}
	order = []
	models = set()
	for name in indents:
		ind = frappe.get_doc("Indent", name)
		for row in ind.items:
			if row.model:
				models.add(row.model)
			uom = row.uom or "Nos"
			key = (row.item_code, uom)
			if key not in agg:
				agg[key] = {"qty": 0.0, "indents": set(), "model": row.model,
				            "required_date": row.required_date}
				order.append(key)
			agg[key]["qty"] += flt(row.qty)
			agg[key]["indents"].add(name)

	plan = frappe.new_doc("Purchase Plan")
	plan.plan_date = nowdate()
	plan.indent_refs = ", ".join(indents)
	for (item_code, uom) in order:
		d = agg[(item_code, uom)]
		plan.append("items", {
			"item_code": item_code,
			"qty": d["qty"],
			"uom": uom,
			"supplier": _default_supplier(item_code),
			"schedule_date": d["required_date"] or add_days(nowdate(), 15),
			"warehouse": RM_STORE,
			"source_indents": ", ".join(sorted(d["indents"])),
			"model": d["model"],
		})
	plan.insert(ignore_permissions=True)

	# carry forward the forgotten-component reconciliation as a heads-up.
	warnings = _reconcile_against_bom(models, {ic for (ic, _u) in order})
	if warnings:
		lines = "; ".join(
			f"{w['model']}: {', '.join(w['missing_from_indent'])}" for w in warnings)
		frappe.msgprint(
			f"Heads-up — BOM components missing from this plan (no stock): {lines}",
			title="BOM Reconciliation", indicator="orange")
	return plan.name


def _indent_names_from_po(doc):
	"""Parse the comma/newline-separated Indent names off a Purchase Order's
	lr_indent_refs field."""
	refs = (doc.get("lr_indent_refs") or "").replace("\n", ",")
	return [n.strip() for n in refs.split(",") if n.strip()]


def mark_indents_ordered(doc, method=None):
	"""PO on_submit: flag the source Indents Ordered so they drop off the pending
	list. Only runs once the PO is actually submitted -- not at fetch time."""
	for name in _indent_names_from_po(doc):
		if frappe.db.exists("Indent", name):
			frappe.db.set_value("Indent", name, "workflow_state", "Ordered")


def unmark_indents_ordered(doc, method=None):
	"""PO on_cancel: return the source Indents to Approved so they can be re-ordered."""
	for name in _indent_names_from_po(doc):
		if frappe.db.exists("Indent", name):
			frappe.db.set_value("Indent", name, "workflow_state", "Approved")
