# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Indent = the Focus 9 rate-less purchase request that sits between Planning and
# the Purchase Order. Multiple approved Indents merge into one PO per supplier
# (common parts like screws summed across orders), with a BOM-reconciliation
# check that flags any model component missing from the consolidated demand.

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


def _default_supplier(item):
	return frappe.db.get_value(
		"Item Default", {"parent": item, "company": COMPANY}, "default_supplier"
	)


@frappe.whitelist()
def make_po_from_indents(indents):
	"""Consolidate multiple Indents into one Purchase Order PER SUPPLIER.
	Common parts (e.g. screws shared by two SOs) are summed onto a single line.
	Returns the created PO names + any BOM-reconciliation warnings."""
	if isinstance(indents, str):
		indents = json.loads(indents)
	if not indents:
		frappe.throw("Select at least one Indent.")

	# aggregate qty by (supplier, item) across all selected indents
	by_supplier = {}
	models = set()
	indent_refs = []
	for name in indents:
		ind = frappe.get_doc("Indent", name)
		indent_refs.append(name)
		for row in ind.items:
			if row.model:
				models.add(row.model)
			supplier = _default_supplier(row.item_code)
			if not supplier:
				continue
			bucket = by_supplier.setdefault(supplier, {})
			bucket[row.item_code] = bucket.get(row.item_code, 0) + flt(row.qty)

	if not by_supplier:
		frappe.throw("None of the indent items have a default supplier set.")

	po_names = []
	for supplier, items in by_supplier.items():
		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": supplier,
			"company": COMPANY,
			"schedule_date": add_days(nowdate(), 15),
			"buying_price_list": "Standard Buying",
			"lr_indent_refs": ", ".join(indent_refs),
			"items": [{
				"item_code": item, "qty": qty, "schedule_date": add_days(nowdate(), 15),
				"warehouse": RM_STORE,
			} for item, qty in items.items()],
		})
		po.insert(ignore_permissions=True)
		po_names.append(po.name)

	# mark the indents as Ordered so they drop off the pending list
	for name in indent_refs:
		frappe.db.set_value("Indent", name, "workflow_state", "Ordered")

	warnings = _reconcile_against_bom(models, by_supplier)
	return {"purchase_orders": po_names, "reconciliation": warnings}


def _reconcile_against_bom(models, by_supplier):
	"""Flag any component in a model's BOM that is NOT present in the
	consolidated PO demand -- the client's 1-2 hr manual screw-reconciliation,
	automated."""
	ordered_items = {item for items in by_supplier.values() for item in items}
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
