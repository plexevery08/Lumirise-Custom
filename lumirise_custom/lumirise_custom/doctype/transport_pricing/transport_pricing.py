import frappe
from frappe import _
from frappe.model.document import Document


class TransportPricing(Document):
	def validate(self):
		self.ensure_unique()

	def ensure_unique(self):
		"""Composite uniqueness on item + transport_type + transport_zone (mirrors the Supabase unique constraint)."""
		filters = {"item": self.item, "transport_type": self.transport_type, "transport_zone": self.transport_zone, "name": ("!=", self.name)}
		if frappe.db.exists("Transport Pricing", filters):
			frappe.throw(_("Transport Pricing already exists for item + transport_type + transport_zone"))
