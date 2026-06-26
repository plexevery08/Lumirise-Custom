# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Vendor PDI = pre-dispatch inspection at the vendor's place (incl. China).
# First gate of the inbound chain: Vendor PDI -> Inbound Logistics -> IQC -> GRN.
# No stock moves here (goods are at the vendor, not owned yet) — the qty is tracked
# as a live segment of the open PO qty in Material Planning. The status flow
# (PDI Scheduled -> PDI In Progress -> PDI Passed -> Dispatched) is driven by the
# form buttons; Logistics is created MANUALLY once status = Dispatched.
# Focus rule: accepted qty can never exceed the PO qty (less is allowed).

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# --- Status values (single source of truth) ---------------------------------
SCHEDULED = "PDI Scheduled"
IN_PROGRESS = "PDI In Progress"
PASSED = "PDI Passed"
DISPATCHED = "Dispatched"
ON_HOLD = "On Hold"
FAILED = "Failed"


class VendorPDI(Document):
	def validate(self):
		if not self.status:
			self.status = SCHEDULED
		any_reject = False
		for row in self.items:
			po_qty = flt(frappe.db.get_value(
				"Purchase Order Item",
				{"parent": self.purchase_order, "item_code": row.item_code}, "qty"))
			if po_qty:
				row.po_qty = po_qty
			if flt(row.approved_qty) < 0 or flt(row.rejected_qty) < 0:
				frappe.throw(_("Row {0} ({1}): Accepted / Rejected qty cannot be negative.").format(row.idx, row.item_code))
			if flt(row.approved_qty) + flt(row.rejected_qty) > flt(row.po_qty) + 0.001:
				frappe.throw(_("Row {0} ({1}): Accepted + Rejected ({2}) cannot exceed PO Qty {3}.").format(
					row.idx, row.item_code, flt(row.approved_qty) + flt(row.rejected_qty), row.po_qty))
			row.pending_qty = flt(row.po_qty) - flt(row.approved_qty) - flt(row.rejected_qty)
			row.result = "Fail" if flt(row.rejected_qty) > 0 else "Pass"
			if flt(row.rejected_qty) > 0:
				any_reject = True
		# Reflect the inspection outcome in the header status while still in progress.
		if self.status in (SCHEDULED, IN_PROGRESS):
			self.status = FAILED if (any_reject and all(flt(r.approved_qty) == 0 for r in self.items)) else self.status


# --- flow transitions (called from the form buttons) ------------------------
def _load(docname):
	return frappe.get_doc("Vendor PDI", docname)


@frappe.whitelist()
def start_inspection(docname):
	"""Quality begins the vendor inspection."""
	frappe.has_permission("Vendor PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.status not in (SCHEDULED, ON_HOLD):
		frappe.throw(_("Only a Scheduled / On-Hold Vendor PDI can start inspection."))
	doc.db_set("status", IN_PROGRESS)
	return {"status": IN_PROGRESS}


@frappe.whitelist()
def record_result(docname):
	"""Quality records the per-line accepted / rejected qty (entered in the grid)
	and marks the inspection Passed (or Failed if everything was rejected)."""
	frappe.has_permission("Vendor PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.status not in (IN_PROGRESS, SCHEDULED):
		frappe.throw(_("Record the result from an in-progress Vendor PDI."))
	all_rejected = all(flt(r.approved_qty) == 0 for r in doc.items)
	doc.db_set("status", FAILED if all_rejected else PASSED)
	return {"status": doc.status}


@frappe.whitelist()
def dispatch(docname):
	"""Vendor PDI passed and the accepted goods are dispatched. Sets the status that
	makes the 'Create > Inbound Logistics' action available (no auto-creation)."""
	frappe.has_permission("Vendor PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.status != PASSED:
		frappe.throw(_("Record a passed result before dispatching."))
	if not any(flt(r.approved_qty) > 0 for r in doc.items):
		frappe.throw(_("Nothing accepted to dispatch."))
	doc.db_set("status", DISPATCHED)
	return {"status": DISPATCHED}


@frappe.whitelist()
def hold(docname, reason=None):
	frappe.has_permission("Vendor PDI", "write", docname, throw=True)
	doc = _load(docname)
	doc.db_set("status", ON_HOLD)
	if reason:
		doc.db_set("pdi_remarks", reason)
	return {"status": ON_HOLD}
