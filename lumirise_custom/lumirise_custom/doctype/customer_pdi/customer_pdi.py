# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Customer PDI = pre-dispatch inspection with the customer (video sign-off).
# A submitted Customer PDI with sign-off = Pass is what unlocks the Delivery Note
# for that Sales Order (gate in events.py).

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CustomerPDI(Document):
	def validate(self):
		if flt(self.sampled_qty) <= 0:
			frappe.throw("Sampled Qty must be greater than zero.")
		# default a standard check sheet if the inspector left it empty
		if not self.checks:
			for p in ["Glow / Lumen", "Wattage / CCT", "Packaging & Master Box",
					  "Screws & Fitment", "Internal Label / Print", "Box Serial / K-slot Count"]:
				self.append("checks", {"parameter": p, "result": "Accepted"})

	def before_submit(self):
		if not self.customer_signoff:
			frappe.throw("Set the Customer Sign-off (Pass / Fail) before submitting.")
		if any(c.result == "Rejected" for c in self.checks) and self.customer_signoff == "Pass":
			frappe.throw("A check is marked Rejected — sign-off cannot be Pass.")

	def on_submit(self):
		if self.customer_signoff == "Fail":
			frappe.msgprint("PDI failed — rework required before dispatch.",
							indicator="red", alert=True)
