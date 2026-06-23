"""Material Receipt -- the factory's acknowledgement of RM issued from the store.

Ajay review 2026-06-14 (00:48:43-00:54:46): after the RM store issues material to
the shop floor, "the person who is taking material in factory should do the receipt
note... once he acknowledged, he cannot say no." This gives clear accountability for
the hand-off and a record when counts mismatch -- the "fight" Ajay described.

The physical stock already moved (the issue Stock Entry). This document is the
binding sign-off; if the factory counts a shortfall it is captured and a task is
raised to Stores so nothing is silently lost.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class MaterialReceipt(Document):
	def validate(self):
		for row in self.items:
			row.shortfall_qty = flt(row.issued_qty) - flt(row.received_qty)

	def on_submit(self):
		self.db_set("acknowledged", 1)
		shortfalls = [r for r in self.items if flt(r.shortfall_qty) > 0]
		if shortfalls:
			self._raise_shortfall_task(shortfalls)

	def _raise_shortfall_task(self, shortfalls):
		lines = ", ".join(f"{r.item_code} short {flt(r.shortfall_qty):g}" for r in shortfalls)
		try:
			from lumirise_custom.task_engine import create_task
			create_task(
				title=f"Material shortfall on receipt {self.name}",
				department="Stores - RM",
				task_type="Defect / Rejection",
				priority="High",
				reference_doctype="Material Receipt",
				reference_name=self.name,
				description=(
					f"Factory acknowledged receipt {self.name} with a shortfall: {lines}. "
					f"Reconcile the issue (Stock Entry {self.source_stock_entry or '-'}) "
					f"with the factory count."
				),
				source_event="material_receipt_shortfall",
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Material Receipt shortfall task failed")


@frappe.whitelist()
def make_material_receipt(source_name, target_doc=None):
	"""Build a Material Receipt prefilled from a 'Material Issue to Shop Floor' Stock
	Entry, for the factory store manager to acknowledge. issued_qty = the qty moved;
	received_qty defaults to the same and is edited to the actual count."""
	se = frappe.get_doc("Stock Entry", source_name)
	mr = frappe.new_doc("Material Receipt")
	mr.source_stock_entry = se.name
	mr.work_order = se.get("work_order")
	target = ""
	for it in se.items:
		target = target or it.t_warehouse
		mr.append("items", {
			"item_code": it.item_code,
			"issued_qty": flt(it.qty),
			"received_qty": flt(it.qty),
			"uom": it.uom or "Nos",
		})
	mr.from_warehouse = target
	return mr
