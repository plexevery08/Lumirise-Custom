# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Child table on IQC — one row per pre-GRN sample drawn for testing. All business
# logic (issue / realise to lab / return) lives in lumirise_custom.samples so the
# same flow can be driven from the form buttons and from the GRN doc-event.

from frappe.model.document import Document


class IQCSample(Document):
	pass
