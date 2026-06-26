# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# IQC = Incoming Quality Control at the factory. Third/last inbound gate before
# the GRN (standard Purchase Receipt). Unlike Focus, rejections are tracked here
# (qty + reason + disposition) instead of silently sitting "pending".
# A submitted IQC with accepted qty is what unlocks the GRN (see events.py).
#
# No stock moves here (goods are on the dock, not owned) — the accepted qty is a
# live segment of the open PO qty in Material Planning ("Pending IQC") until the
# GRN posts, which flips the status to "Moved to RM" and lands the stock in the RM
# store (see chain.mark_iqc_moved_to_rm wired on Purchase Receipt submit).
# Status flow: IQC Received -> Testing -> Passed -> Moved to RM (+ On Hold / Rejected).

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# --- Status values (single source of truth) ---------------------------------
RECEIVED = "IQC Received"
TESTING = "Testing"
PASSED = "Passed"
MOVED_TO_RM = "Moved to RM"
ON_HOLD = "On Hold"
REJECTED = "Rejected"


class IQC(Document):
	def validate(self):
		if not self.status:
			self.status = RECEIVED
		any_reject = False
		for row in self.items:
			parts = (flt(row.accepted_qty) + flt(row.rejected_qty)
			         + flt(row.under_test_qty) + flt(row.on_hold_qty))
			if parts > flt(row.received_qty) + 0.001:
				frappe.throw(
					f"Row {row.idx} ({row.item_code}): accepted + rejected + under-test "
					f"+ on-hold cannot exceed received qty.")
			if flt(row.rejected_qty) > 0:
				any_reject = True
				if not row.disposition:
					frappe.throw(
						f"Row {row.idx} ({row.item_code}): set a Disposition "
						f"(Return to Vendor / Replace / Scrap) for the rejected qty.")
		# auto-set the overall result
		if not any_reject:
			self.result = "Accepted"
		elif all(flt(r.accepted_qty) == 0 for r in self.items):
			self.result = "Rejected"
		else:
			self.result = "Partial"

	def on_submit(self):
		# Lock the header status to the inspection outcome on submit (unless the
		# inspector parked it On Hold).
		if self.status not in (ON_HOLD, MOVED_TO_RM):
			self.db_set("status", REJECTED if self.result == "Rejected" else PASSED)
		if self.result == "Rejected":
			frappe.msgprint(
				"All quantities rejected — no GRN can be raised against this IQC.",
				indicator="red", alert=True)


# --- flow transitions (called from the form buttons) ------------------------
def _load(docname):
	return frappe.get_doc("IQC", docname)


@frappe.whitelist()
def start_testing(docname):
	"""Quality begins incoming inspection / testing."""
	frappe.has_permission("IQC", "write", docname, throw=True)
	doc = _load(docname)
	if doc.status not in (RECEIVED, ON_HOLD):
		frappe.throw(_("Only a received / on-hold IQC can start testing."))
	doc.db_set("status", TESTING)
	return {"status": TESTING}


@frappe.whitelist()
def record_result(docname):
	"""Quality records the per-line accepted / rejected qty (entered in the grid)
	and marks the IQC Passed (or Rejected if everything failed)."""
	frappe.has_permission("IQC", "write", docname, throw=True)
	doc = _load(docname)
	if doc.status not in (RECEIVED, TESTING):
		frappe.throw(_("Record the result from a received / in-testing IQC."))
	all_rejected = all(flt(r.accepted_qty) == 0 for r in doc.items)
	doc.db_set("status", REJECTED if all_rejected else PASSED)
	return {"status": doc.status}


@frappe.whitelist()
def hold(docname, reason=None):
	frappe.has_permission("IQC", "write", docname, throw=True)
	doc = _load(docname)
	doc.db_set("status", ON_HOLD)
	if reason:
		doc.db_set("iqc_remarks", reason)
	return {"status": ON_HOLD}
