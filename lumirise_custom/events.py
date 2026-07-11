# Cross-doctype gates that enforce the Focus 9 quality flow on STANDARD ERPNext
# documents (we own these via doc_events in hooks.py, not by editing ERPNext):
#   - Purchase Receipt (= GRN) cannot submit until a passed IQC exists for its PO.
#   - Delivery Note (= Dispatch) cannot submit until a passed Customer PDI exists
#     for its Sales Order.

import frappe

from lumirise_custom import defaults as config


def container_release_gate(doc, method=None):
	"""Warn/block a GRN whose PO's Inbound Logistics has not been released by Purchase.
	Strength is config-driven (Lumirise Operations Settings.block_grn_without_container_
	release, default OFF = warn + a Purchase task; ON = hard block). Skips subcontracting
	and domestic direct receipts (a PO with no Inbound Logistics)."""
	if doc.get("is_subcontracted"):
		return
	pos = {row.purchase_order for row in doc.items if getattr(row, "purchase_order", None)}
	unreleased = []
	for po in pos:
		logs = frappe.get_all(
			"Inbound Logistics",
			filters={"purchase_order": po, "docstatus": 1},
			fields=["name", "release_status"],
		)
		if logs and not any((l.release_status == "Released") for l in logs):
			unreleased.append((po, logs[0].name))
	if not unreleased:
		return
	detail = ", ".join(f"PO {po} (logistics {log})" for po, log in unreleased)
	if config.flag("block_grn_without_container_release", default=False):
		frappe.throw(
			f"Container not released by Purchase for: {detail}. "
			f"Release the Inbound Logistics before the GRN.",
			title="Container Release Gate",
		)
	# soft mode: let the GRN through but flag it to Purchase
	frappe.msgprint(
		f"Container not yet released by Purchase for: {detail}.",
		title="Container Release", indicator="orange",
	)
	try:
		from lumirise_custom.task_engine import create_task

		for po, log in unreleased:
			create_task(
				title=f"Confirm container release — {log} (PO {po})",
				department="Purchase",
				task_type="Handoff",
				priority="Medium",
				reference_doctype="Inbound Logistics",
				reference_name=log,
				description=f"A GRN was posted for PO {po} before its Inbound Logistics {log} was released. Confirm/authorize.",
				source_event="container_release_pending",
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "container_release_gate: task failed")


PACKING_APPROVER_ROLES = ("Factory Store Manager", "System Manager")


def packing_gate(doc, method=None):
	"""Block a Delivery Note submit until packing is approved — ONLY when Lumirise
	Operations Settings.require_packing_approval is ON (default OFF). Inert otherwise."""
	if not config.flag("require_packing_approval", default=False):
		return
	if not doc.get("lr_packing_approved"):
		frappe.throw(
			"Packing is not approved for this Delivery Note. A Factory Store Manager "
			"must approve packing before dispatch.",
			title="Packing Approval Gate",
		)


@frappe.whitelist()
def approve_packing(delivery_note):
	"""Factory Store Manager signs off packing on a (draft) Delivery Note."""
	frappe.has_permission("Delivery Note", "write", delivery_note, throw=True)
	if not any(r in frappe.get_roles() for r in PACKING_APPROVER_ROLES):
		frappe.throw("Only a Factory Store Manager can approve packing.")
	doc = frappe.get_doc("Delivery Note", delivery_note)
	if doc.docstatus != 0:
		frappe.throw("Approve packing while the Delivery Note is still a draft.")
	doc.db_set("lr_packing_approved", 1)
	doc.db_set("lr_packing_approved_by", frappe.session.user)
	return {"lr_packing_approved": 1}


def iqc_gate(doc, method=None):
	"""Block GRN (Purchase Receipt) submission unless IQC passed for the PO."""
	# Subcontracting job-work billing creates a non-stock Purchase Receipt (for the
	# service charge) from a Subcontracting Receipt. That is NOT an RM GRN — incoming
	# quality is governed on the subcontracting receipt / supplied RM, not here — so
	# the IQC gate must not block it.
	if doc.get("is_subcontracted"):
		return
	pos = {row.purchase_order for row in doc.items if getattr(row, "purchase_order", None)}
	for po in pos:
		iqc = frappe.get_all(
			"IQC",
			filters={"purchase_order": po, "docstatus": 1, "result": ["!=", "Rejected"]},
			limit=1)
		if not iqc:
			frappe.throw(
				f"IQC not cleared for Purchase Order <b>{po}</b>. "
				f"Goods cannot enter stock until Incoming Quality Control passes "
				f"(Vendor PDI → Logistics → IQC → GRN).",
				title="IQC Gate")


def customer_pdi_gate(doc, method=None):
	"""Block Delivery Note (Dispatch) submission unless Customer PDI passed for the SO."""
	sos = {row.against_sales_order for row in doc.items if getattr(row, "against_sales_order", None)}
	for so in sos:
		passed = frappe.get_all(
			"Customer PDI",
			filters={"sales_order": so, "docstatus": 1, "customer_signoff": "Pass"},
			limit=1)
		if not passed:
			frappe.throw(
				f"Customer PDI not passed for Sales Order <b>{so}</b>. "
				f"The lot cannot be dispatched until pre-dispatch inspection is signed off.",
				title="Customer PDI Gate")
