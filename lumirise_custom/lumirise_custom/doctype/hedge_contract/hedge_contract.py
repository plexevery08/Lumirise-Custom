import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate


class HedgeContract(Document):
	def validate(self):
		if getdate(self.maturity_date) < getdate(self.start_date):
			frappe.throw("Maturity Date cannot be before Start Date.")
		if flt(self.utilised_amount) > flt(self.hedged_amount):
			frappe.throw("Utilised Amount cannot exceed the Hedged Amount.")
		if flt(self.utilised_amount) == flt(self.hedged_amount) and self.status == "Active":
			self.status = "Utilised"
