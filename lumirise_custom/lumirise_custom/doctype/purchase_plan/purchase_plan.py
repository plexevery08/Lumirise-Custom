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
def get_indent_qty(plan_name=None, indent_refs=None):
	"""Total indented qty per item across the plan's source Indents — the baseline
	for the Indent-vs-Order balance table (Indent Qty − Order Qty = Balance).
	Returns {item_code: indent_qty}."""
	names = set()
	# Source 1: the plan-level indent_refs (or an explicit override).
	refs = indent_refs
	if not refs and plan_name:
		refs = frappe.db.get_value("Purchase Plan", plan_name, "indent_refs")
	for n in (refs or "").replace("\n", ",").split(","):
		if n.strip():
			names.add(n.strip())
	# Source 2: per-line source_indents (robust if indent_refs is blank).
	if plan_name and frappe.db.exists("Purchase Plan", plan_name):
		for row in frappe.get_all("Purchase Plan Item", filters={"parent": plan_name},
		                          fields=["source_indents"]):
			for n in (row.source_indents or "").replace("\n", ",").split(","):
				if n.strip():
					names.add(n.strip())
	qty = {}
	for name in names:
		if not frappe.db.exists("Indent", name):
			continue
		for row in frappe.get_all("Indent Item", filters={"parent": name},
		                          fields=["item_code", "qty"]):
			qty[row.item_code] = flt(qty.get(row.item_code, 0)) + flt(row.qty)
	return qty


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
