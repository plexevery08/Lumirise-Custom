# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Inbound Logistics = the transit/LR step between Vendor PDI and IQC. Carries the
# LR number, vehicle, transporter and container. Second gate of the inbound chain.
# No stock moves here (goods are in transit, not owned) — the qty is a live segment
# of the open PO qty in Material Planning, measured by the status below:
#   Dispatched / In Transit  -> counts as "In Transit"
#   Reached Warehouse        -> counts as "Pending IQC"
# IQC is created MANUALLY via the Create button once status = Reached Warehouse.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# --- Status values (single source of truth) ---------------------------------
DISPATCHED = "Dispatched"
IN_TRANSIT = "In Transit"
REACHED = "Reached Warehouse"


class InboundLogistics(Document):
	def validate(self):
		if not self.status:
			self.status = DISPATCHED
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


# --- flow transitions (called from the form buttons) ------------------------
def _load(docname):
	return frappe.get_doc("Inbound Logistics", docname)


@frappe.whitelist()
def mark_in_transit(docname):
	"""Logistics confirms the consignment has left the vendor / port."""
	frappe.has_permission("Inbound Logistics", "write", docname, throw=True)
	doc = _load(docname)
	if doc.status not in (DISPATCHED, IN_TRANSIT):
		frappe.throw(_("Only a Dispatched consignment can be marked In Transit."))
	doc.db_set("status", IN_TRANSIT)
	return {"status": IN_TRANSIT}


@frappe.whitelist()
def mark_reached(docname):
	"""Consignment has reached the factory dock — qty moves In-Transit -> Pending
	IQC (derived). Makes the 'Create > IQC' action the next step (no auto-create)."""
	frappe.has_permission("Inbound Logistics", "write", docname, throw=True)
	doc = _load(docname)
	if doc.status not in (DISPATCHED, IN_TRANSIT, REACHED):
		frappe.throw(_("Mark a dispatched / in-transit consignment as reached."))
	doc.db_set("status", REACHED)
	return {"status": REACHED}
