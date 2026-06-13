"""Sales Order status sync.

Writes the (previously dead) Sales Order tracking fields so anyone can see where
an order is without chasing people:

    lr_planning_status   : Pending -> Planned
    lr_purchase_status   : Pending -> Indented -> Ordered -> Received
    lr_production_status : Pending -> In Production -> Completed

Driven off the real lifecycle events (plan posted, work order, PO, GRN). Status
only ever ADVANCES — a later cancel/edit never silently regresses it here.

FAIL-SAFE: a status write can never roll back the business document. Uses
frappe.db.set_value (no controller re-trigger, no costing/task re-fire).
"""

import frappe

# Forward-only rank maps (matching the Select field options exactly).
PLANNING_RANK = {"": 0, "Pending": 0, "Planned": 1}
PURCHASE_RANK = {"": 0, "Pending": 0, "Indented": 1, "Ordered": 2, "Received": 3}
PRODUCTION_RANK = {"": 0, "Pending": 0, "In Production": 1, "Completed": 2}


def _advance(so, field, value, rank):
	try:
		if not so or not frappe.db.exists("Sales Order", so):
			return
		current = frappe.db.get_value("Sales Order", so, field) or ""
		if rank.get(value, 0) > rank.get(current, 0):
			frappe.db.set_value("Sales Order", so, field, value, update_modified=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Status sync: {field} failed for {so}")


def set_planning(so, value):
	_advance(so, "lr_planning_status", value, PLANNING_RANK)


def set_purchase(so, value):
	_advance(so, "lr_purchase_status", value, PURCHASE_RANK)


def set_production(so, value):
	_advance(so, "lr_production_status", value, PRODUCTION_RANK)


# --------------------------------------------------------------------- resolvers
def _sos_from_planning(doc):
	sos = set()
	for fg in doc.get("fg_plan") or []:
		if fg.get("sales_order"):
			sos.add(fg.get("sales_order"))
	return sos


def _sos_from_indents(indent_names):
	sos = set()
	for ind in indent_names:
		if not ind or not frappe.db.exists("Indent", ind):
			continue
		head = frappe.db.get_value("Indent", ind, "source_sales_order")
		if head:
			sos.add(head)
		for so in frappe.get_all("Indent Item", filters={"parent": ind}, pluck="for_sales_order"):
			if so:
				sos.add(so)
	return sos


def _sos_from_po(po):
	"""PO -> the Indents it consumed (lr_indent_refs) -> their Sales Orders."""
	refs = frappe.db.get_value("Purchase Order", po, "lr_indent_refs") or ""
	indents = [r.strip() for r in refs.replace(",", " ").split() if r.strip()]
	return _sos_from_indents(indents)


# --------------------------------------------------------------------- handlers
def on_material_planning_submit(doc, method=None):
	"""Plan posted -> SOs are Planned; the consolidated Indent makes them Indented."""
	try:
		sos = _sos_from_planning(doc)
		for so in sos:
			set_planning(so, "Planned")
		if doc.get("created_indent"):
			for so in sos:
				set_purchase(so, "Indented")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Status sync: on_material_planning_submit failed")


def on_work_order_submit(doc, method=None):
	"""Work Order released -> the order is In Production."""
	if doc.get("sales_order"):
		set_production(doc.get("sales_order"), "In Production")


def on_work_order_update(doc, method=None):
	"""Work Order finished -> production Completed."""
	if doc.get("sales_order") and doc.get("status") == "Completed":
		set_production(doc.get("sales_order"), "Completed")


def on_purchase_order_submit(doc, method=None):
	"""PO submitted against the indent(s) -> the order is Ordered."""
	try:
		for so in _sos_from_po(doc.name):
			set_purchase(so, "Ordered")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Status sync: on_purchase_order_submit failed")


def on_purchase_receipt_submit(doc, method=None):
	"""GRN posted -> material received against the order."""
	try:
		pos = {r.get("purchase_order") for r in (doc.get("items") or []) if r.get("purchase_order")}
		sos = set()
		for po in pos:
			sos |= _sos_from_po(po)
		for so in sos:
			set_purchase(so, "Received")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Status sync: on_purchase_receipt_submit failed")
