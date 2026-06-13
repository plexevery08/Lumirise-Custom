# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Single settings doc: the one place the Lumirise operations warehouses /
# company / process flags live, so none of it is hard-coded in business logic.
# Resolved through lumirise_custom.config.

import frappe
from frappe.model.document import Document


class LumiriseOperationsSettings(Document):
	pass
