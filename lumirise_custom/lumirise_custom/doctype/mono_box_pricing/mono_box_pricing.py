import frappe
from frappe import _
from frappe.model.document import Document


class MonoBoxPricing(Document):
	def validate(self):
		self.ensure_unique()
		self.ensure_box_finish()

	def ensure_unique(self):
		"""Composite uniqueness on item + box_finish + moq (mirrors the Supabase unique constraint)."""
		filters = {"item": self.item, "box_finish": self.box_finish, "moq": self.moq, "name": ("!=", self.name)}
		if frappe.db.exists("Mono Box Pricing", filters):
			frappe.throw(_("Mono Box Pricing already exists for item + box_finish + moq"))

	def ensure_box_finish(self):
		"""Box Finish master backs the Price Sheet link fields; create on demand
		so bulk imports of pricing rows never fail link validation."""
		if self.box_finish and not frappe.db.exists("Box Finish", self.box_finish):
			frappe.get_doc(
				{"doctype": "Box Finish", "finish_name": self.box_finish}
			).insert(ignore_permissions=True)
