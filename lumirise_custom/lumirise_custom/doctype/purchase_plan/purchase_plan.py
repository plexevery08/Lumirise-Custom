"""Purchase Plan -- the merge-indents → assign-vendor → split-PO-by-vendor step.

Ajay review 2026-06-14 (transcript 00:21:00-00:30:41): multiple Indents must be
merged (qty summed per item), a vendor assigned per item, and then ONE Purchase
Order generated PER VENDOR so volume aggregation unlocks price slabs (₹9 @ 200pcs
vs ₹10 @ 100pcs). Created from the Indent list via indent.make_purchase_plan().

The generated POs land in Draft and go through the Purchase Order Release workflow
(Purchase Head approval) added in approval_setup.py -- matching Ajay's "for purchase
head, purchase order releasing, approval should be needed."
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

RM_STORE = "Stores - L"


class PurchasePlan(Document):
	def before_submit(self):
		"""Every consolidated line must have a vendor before the plan is released for
		PO generation -- that is the whole point of this step."""
		missing = [d.item_code for d in self.items if not d.supplier]
		if missing:
			frappe.throw(
				_("Assign a Supplier (vendor) to every line before submitting. "
				  "Missing for: {0}").format(", ".join(missing))
			)


@frappe.whitelist()
def create_purchase_orders(plan_name):
	"""Group the plan's lines by supplier and create one Draft Purchase Order per
	supplier. Returns the list of created PO names. Idempotent guard: refuses to run
	twice on the same submitted plan."""
	plan = frappe.get_doc("Purchase Plan", plan_name)
	if plan.docstatus != 1:
		frappe.throw(_("Submit the Purchase Plan before creating Purchase Orders."))
	if plan.po_status == "POs Created":
		frappe.throw(_("Purchase Orders were already created for this plan: {0}").format(
			plan.created_pos or ""))

	# group rows by supplier, preserving the union of source indents per supplier
	by_supplier = {}
	for row in plan.items:
		if not row.supplier:
			frappe.throw(_("Row {0} ({1}) has no supplier.").format(row.idx, row.item_code))
		bucket = by_supplier.setdefault(row.supplier, {"rows": [], "indents": set()})
		bucket["rows"].append(row)
		for ind in (row.source_indents or "").replace(" ", "").split(","):
			if ind:
				bucket["indents"].add(ind)

	created = []
	for supplier, bucket in by_supplier.items():
		po = frappe.new_doc("Purchase Order")
		po.supplier = supplier
		po.lr_indent_refs = ", ".join(sorted(bucket["indents"]))
		for row in bucket["rows"]:
			po.append("items", {
				"item_code": row.item_code,
				"item_name": row.item_name or row.item_code,
				"qty": flt(row.qty),
				"uom": row.uom or "Nos",
				"stock_uom": row.uom or "Nos",
				"conversion_factor": 1,
				"schedule_date": row.schedule_date or frappe.utils.add_days(frappe.utils.nowdate(), 15),
				"warehouse": row.warehouse or RM_STORE,
			})
		# Leave the PO in Draft -- Purchase Head releases it via the workflow.
		po.insert(ignore_permissions=True)
		created.append(po.name)

	plan.db_set("po_status", "POs Created")
	plan.db_set("created_pos", ", ".join(created))
	return created
