# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Department -> Supervisor + HOD reporting map. Drives auto-assignment and
# supervisor/HOD tagging in the Lumirise task engine (see task_engine.py).
# Seeded from the discovery-call transcripts; the User links are filled in by
# the admin once the matching ERPNext logins exist.

import frappe
from frappe.model.document import Document


class LumiriseDepartmentMap(Document):
	pass
