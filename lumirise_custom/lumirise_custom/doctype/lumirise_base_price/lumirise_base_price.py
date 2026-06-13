import frappe
from frappe import _
from frappe.model.document import Document


class LumiriseBasePrice(Document):
	def validate(self):
		self.ensure_unique()

	def ensure_unique(self):
		"""Composite uniqueness on item + moq (mirrors the Supabase unique constraint)."""
		filters = {"item": self.item, "moq": self.moq, "name": ("!=", self.name)}
		if frappe.db.exists("Lumirise Base Price", filters):
			frappe.throw(_("Lumirise Base Price already exists for item + moq"))
