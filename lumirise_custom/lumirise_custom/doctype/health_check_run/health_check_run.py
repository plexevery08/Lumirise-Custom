# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Health Check Run = one daily self-test snapshot (header + results child table).
# Built and inserted by lumirise_custom.health_check; not created by hand.

from frappe.model.document import Document


class HealthCheckRun(Document):
	pass
