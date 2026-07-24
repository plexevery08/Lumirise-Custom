import frappe
from frappe.model.document import Document


class BitrixSyncSettings(Document):
	def validate(self):
		if self.enabled and not (self.webhook_url or "").startswith("https://"):
			frappe.throw("Webhook URL must be a https Bitrix24 inbound-webhook URL before enabling.")
		if self.webhook_url and not self.webhook_url.endswith("/"):
			self.webhook_url += "/"
