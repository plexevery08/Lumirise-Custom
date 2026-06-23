# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Health Check Result = one assertion verdict inside a Health Check Run (child
# table). Populated by lumirise_custom.health_check; never edited by hand.

from frappe.model.document import Document


class HealthCheckResult(Document):
	pass
