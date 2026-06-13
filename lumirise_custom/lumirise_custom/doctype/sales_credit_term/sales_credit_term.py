import frappe
from frappe import _
from frappe.model.document import Document


class SalesCreditTerm(Document):
	def validate(self):
		self.ensure_unique()
		self.title = (
			"Advance"
			if self.payment_type == "Advance"
			else f"Credit {self.credit_days} Days ({self.percentage}%)"
		)

	def ensure_unique(self):
		"""Composite uniqueness on payment_type + credit_days (mirrors the Supabase unique constraint)."""
		filters = {"payment_type": self.payment_type, "credit_days": self.credit_days, "name": ("!=", self.name)}
		if frappe.db.exists("Sales Credit Term", filters):
			frappe.throw(_("Sales Credit Term already exists for payment_type + credit_days"))
