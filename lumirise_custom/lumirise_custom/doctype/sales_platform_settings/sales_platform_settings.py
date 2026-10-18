from frappe.model.document import Document


class SalesPlatformSettings(Document):
	def on_update(self):
		from lumirise_custom.costing import on_costing_settings_update

		on_costing_settings_update(self)
