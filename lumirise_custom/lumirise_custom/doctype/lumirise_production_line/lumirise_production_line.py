"""Child table row: one physical production/assembly line, modelled as a
Warehouse so per-line stock is visible (matches the Focus 9 model where each line
is its own stock location)."""

from frappe.model.document import Document


class LumiriseProductionLine(Document):
	pass
