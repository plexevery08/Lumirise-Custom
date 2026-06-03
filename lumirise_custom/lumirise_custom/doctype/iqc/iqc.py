# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# IQC = Incoming Quality Control at the factory. Third/last inbound gate before
# the GRN (standard Purchase Receipt). Unlike Focus, rejections are tracked here
# (qty + reason + disposition) instead of silently sitting "pending".
# A submitted IQC with accepted qty is what unlocks the GRN (see events.py).

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class IQC(Document):
	def validate(self):
		any_reject = False
		for row in self.items:
			if flt(row.accepted_qty) + flt(row.rejected_qty) > flt(row.received_qty) + 0.001:
				frappe.throw(
					f"Row {row.idx} ({row.item_code}): accepted + rejected "
					f"cannot exceed received qty.")
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
		if self.result == "Rejected":
			frappe.msgprint(
				"All quantities rejected — no GRN can be raised against this IQC.",
				indicator="red", alert=True)
