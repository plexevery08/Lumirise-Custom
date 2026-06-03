# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Inbound Logistics = the transit/LR step between Vendor PDI and IQC. Carries the
# LR number, vehicle, transporter and container. Second gate of the inbound chain.

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class InboundLogistics(Document):
	def validate(self):
		# approved-at-PDI qty is the ceiling for what can be in transit
		approved = {
			d.item_code: flt(d.approved_qty)
			for d in frappe.get_all(
				"Vendor PDI Item", {"parent": self.vendor_pdi},
				["item_code", "approved_qty"]) or []
		}
		for row in self.items:
			cap = approved.get(row.item_code)
			if cap is not None and flt(row.qty) > cap:
				frappe.throw(
					f"Row {row.idx} ({row.item_code}): logistics qty {row.qty} "
					f"cannot exceed the Vendor-PDI approved qty {cap}.")
