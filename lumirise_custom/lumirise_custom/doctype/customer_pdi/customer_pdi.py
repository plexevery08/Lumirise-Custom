# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Customer PDI = pre-dispatch inspection with the customer (video sign-off).
# A submitted Customer PDI with sign-off = Pass is what unlocks the Delivery Note
# for that Sales Order (gate in events.py).
#
# Stock movement (matches the Focus 9 / FG-stores process): the sampled qty is
# physically drawn from the Dispatch FG store into a dedicated Customer PDI store
# for the video inspection. On Pass it returns to Dispatch FG (net zero, full audit
# trail); on Fail it routes to the Rejection store (the failed sample leaves
# dispatchable stock). All movements keep stock accurate.

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from lumirise_custom import defaults as config


class CustomerPDI(Document):
	def validate(self):
		if flt(self.sampled_qty) <= 0:
			frappe.throw("Sampled Qty must be greater than zero.")
		# Default the warehouses from Operations Settings (Dispatch FG ↔ PDI store)
		# so we never depend on a hard-coded site-specific warehouse name.
		if not self.source_warehouse:
			self.source_warehouse = config.dispatch_fg_warehouse()
		if not self.pdi_warehouse:
			self.pdi_warehouse = config.pdi_warehouse()
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
		# Draw the sample Dispatch FG -> PDI store, then resolve it by sign-off.
		self._move_stock(self.source_warehouse, self.pdi_warehouse,
						 f"Customer PDI {self.name}: sample drawn for inspection")
		if self.customer_signoff == "Pass":
			self._move_stock(self.pdi_warehouse, self.source_warehouse,
							 f"Customer PDI {self.name}: passed — returned to Dispatch FG")
		else:
			rejection_wh = config.rejection_warehouse(required=False)
			if rejection_wh:
				self._move_stock(self.pdi_warehouse, rejection_wh,
								 f"Customer PDI {self.name}: failed — moved to Rejection")
			frappe.msgprint("PDI failed — rework required before dispatch.",
							indicator="red", alert=True)

	def _move_stock(self, from_wh, to_wh, narration):
		"""Post a submitted Material Transfer of the sampled FG item between two
		warehouses. Raises a clear error if the source lacks the sampled qty."""
		if not (from_wh and to_wh and self.fg_item):
			return
		on_hand = flt(frappe.db.get_value(
			"Bin", {"item_code": self.fg_item, "warehouse": from_wh}, "actual_qty"))
		if on_hand < flt(self.sampled_qty):
			frappe.throw(
				f"Only {on_hand} of {self.fg_item} in {from_wh} — cannot draw a sample "
				f"of {flt(self.sampled_qty)}. Move finished goods to Dispatch FG first.")
		se = frappe.get_doc({
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"company": config.get_company(),
			"from_warehouse": from_wh,
			"to_warehouse": to_wh,
			"custom_narration": narration,
			"items": [{
				"item_code": self.fg_item,
				"qty": flt(self.sampled_qty),
				"s_warehouse": from_wh,
				"t_warehouse": to_wh,
			}],
		})
		se.flags.ignore_permissions = True
		se.insert(ignore_permissions=True)
		se.submit()
