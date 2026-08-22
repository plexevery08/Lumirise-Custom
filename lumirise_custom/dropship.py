# Vendor-to-vendor consignee / RM drop-ship (Rishitha call, 2026-08-17).
#
# Focus 9 flow, her own words: emergency RM only, "directly in the purchase order
# itself, it is not in service order" -- bill to Lumirise, ship to the job-work
# vendor. Store does two entries once the supplier invoice is approved: receive the
# stock, then send it on to the other vendor's warehouse. Her ask, verbatim: "such a
# flow is different[,] Service flow is different... these two are not connected. If
# you make these two connected, it means it would be really easy" -- so the Consignee
# field resolves the open Subcontracting Order for that vendor and the transfer is
# tagged to it, keeping the existing shortfall/theft tracking intact for drop-shipped
# material exactly like it already works for material sent the normal way.
#
# Also bundles the RM-Conversion checkpoint the client asked for back in May 2026
# (never built): the outgoing "Send to Subcontractor" leg is created as a DRAFT, not
# submitted -- see events.dropship_submit_guard for the approval gate.
#
# Design doc: outputs/2026-08-17-consignee-vendor-to-vendor-proposed-solution.md

import frappe
from frappe.utils import flt

from lumirise_custom import defaults as config

OPEN_SCO_STATUSES = ["Draft", "Open", "Partial Material Transferred", "Material Transferred",
					  "Partially Received"]


@frappe.whitelist()
def get_open_subcontracting_orders(supplier):
	"""Open Subcontracting Orders for this vendor -- lets the Consignee field on the
	Purchase Order resolve (or offer a pick-list for) which job the drop-shipped RM
	is for. Called from purchase_order.js on the Consignee field change."""
	if not supplier:
		return []
	return frappe.get_all(
		"Subcontracting Order",
		filters={"supplier": supplier, "docstatus": 1, "status": ["in", OPEN_SCO_STATUSES]},
		fields=["name", "status", "supplier_warehouse", "transaction_date"],
		order_by="transaction_date desc",
	)


@frappe.whitelist()
def get_sco_bom_summary(sco_name):
	"""Rishitha's follow-up (2026-08-22 walkthrough): "can you do that with child BOMs...
	it would be easier for us to track" -- she wants to see, right on the PO, which child
	BOM / semi-finished item this drop-shipped RM is destined to become, not just the
	Subcontracting Order name. Called from purchase_order.js straight after
	lr_consignee_sco_ref is resolved, to fill lr_consignee_bom_ref.

	One SCO can carry more than one FG item row (each with its own bom) -- join all of
	them so nothing's silently dropped."""
	if not sco_name:
		return ""
	rows = frappe.get_all(
		"Subcontracting Order Item",
		filters={"parent": sco_name},
		fields=["bom", "item_code"],
	)
	return ", ".join(f"{row.bom} -> {row.item_code}" for row in rows if row.bom)


@frappe.whitelist()
def receive_and_forward(purchase_order):
	"""'Receive & Forward to Consignee' -- the one-click bridge for Store.

	Posts the two entries Rishitha described as manual: (1) a normal Purchase Receipt
	against the RM warehouse (makes the supplier payable via the standard PO->GRN->PI
	chain), then (2) the "Send to Subcontractor" transfer from that warehouse into the
	consignee vendor's Job Worker Warehouse, tagged to the linked Subcontracting Order.
	The transfer is inserted as a DRAFT -- it does not move stock or register with the
	Subcontracting Order's own supply ledger until an approver submits it (the RM-
	Conversion checkpoint). Route-don't-insert stops at the GRN; the transfer is
	deliberately left for a human to review, that IS the checkpoint.
	"""
	po = frappe.get_doc("Purchase Order", purchase_order)
	if po.docstatus != 1:
		frappe.throw("The Purchase Order must be submitted first.")
	if not po.get("lr_consignee"):
		frappe.throw("Set the <b>Consignee</b> vendor on this Purchase Order first.")
	sco_name = po.get("lr_consignee_sco_ref")
	if not sco_name:
		frappe.throw(
			"No Subcontracting Order is linked yet. Re-select the Consignee to resolve "
			"(or pick) the job this RM is for.")
	sco = frappe.get_doc("Subcontracting Order", sco_name)
	if sco.docstatus != 1:
		frappe.throw(f"Subcontracting Order {sco_name} is not submitted.")
	if not sco.supplier_warehouse:
		frappe.throw(
			f"Subcontracting Order {sco_name} has no Job Worker Warehouse set -- "
			f"set one there first.")

	rm_warehouse = config.rm_warehouse()

	existing_pr = frappe.get_all(
		"Purchase Receipt Item", filters={"purchase_order": po.name}, pluck="parent", limit=1)
	if existing_pr:
		frappe.throw(f"A Purchase Receipt already exists for this PO ({existing_pr[0]}).")

	# 1. Receive the stock -- standard GRN, makes the vendor payable as normal.
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

	pr = make_purchase_receipt(po.name)
	for row in pr.items:
		row.warehouse = rm_warehouse
	pr.insert(ignore_permissions=True)
	pr.submit()

	# 2. Prepare (do not submit) the transfer onward to the consignee vendor,
	#    tagged to the job it's for. This is the RM-Conversion leg -- the step the
	#    checkpoint gates.
	#
	#    Built off the native mapper (erpnext keeps its own bookkeeping -- required
	#    vs supplied qty per RM item -- on the Subcontracting Order's own "Raw
	#    Materials Supplied" table, and a Send-to-Subcontractor row that isn't tied
	#    back to that table by the fields the mapper sets gets rejected on save).
	#    The mapper proposes the FULL job requirement; a drop-ship GRN may only be
	#    part of it (an emergency partial shipment), so trim to what was actually
	#    just received here and drop everything else.
	from erpnext.controllers.subcontracting_controller import make_rm_stock_entry

	received = {row.item_code: flt(row.qty) for row in pr.items}
	# No rm_items/target_doc passed -> the mapper returns a plain dict, not a
	# Document (erpnext/controllers/subcontracting_controller.py); wrap it.
	se = frappe.get_doc(make_rm_stock_entry(sco.name))
	se.items = [row for row in se.items if row.item_code in received]
	if not se.items:
		frappe.throw(
			f"None of this GRN's items ({', '.join(received)}) are Raw Materials "
			f"Supplied on {sco.name} — check the Consignee's linked job.")
	for row in se.items:
		row.qty = min(flt(row.qty), received[row.item_code])
	se.insert(ignore_permissions=True)

	frappe.msgprint(
		f"Received: {pr.name} (submitted). Forward-to-consignee transfer {se.name} is "
		f"a <b>Draft</b>, pending approval before the RM leaves stock.",
		title="Receive & Forward to Consignee", indicator="green")

	return {"purchase_receipt": pr.name, "stock_entry": se.name}
