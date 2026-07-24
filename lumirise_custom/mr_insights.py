# Material Request insight panel (Phase-2 point 59).
# While raising a Material Requisition against a Production Order, show — for the
# RM item just selected — the five numbers the storekeeper otherwise has to look
# up by hand: store stock, previously requested, already issued, balance still to
# issue, and what the store would hold after issuing that balance.

import frappe
from frappe.utils import flt

from lumirise_custom import defaults as config


@frappe.whitelist()
def mr_item_snapshot(item_code, work_order=None, exclude_mr=None):
	"""Return the requisition context for one RM item (optionally against one
	Work Order). All numbers are read-only lookups — no state is touched."""
	frappe.has_permission("Material Request", "read", throw=True)

	store = config.rm_warehouse()
	available = flt(frappe.db.get_value(
		"Bin", {"item_code": item_code, "warehouse": store}, "actual_qty"))

	required = issued = prev_requested = 0.0
	if work_order and frappe.db.exists("Work Order", work_order):
		row = frappe.db.get_value(
			"Work Order Item",
			{"parent": work_order, "item_code": item_code},
			["required_qty", "transferred_qty"],
			as_dict=True,
		)
		if row:
			required = flt(row.required_qty)
			issued = flt(row.transferred_qty)

		# Previously requested = the same item on OTHER non-cancelled MRs that
		# point at this Production Order (custom field production_order).
		cond = "AND mr.name != %(exclude_mr)s" if exclude_mr else ""
		prev = frappe.db.sql(
			f"""SELECT COALESCE(SUM(mri.qty), 0)
			    FROM `tabMaterial Request Item` mri
			    JOIN `tabMaterial Request` mr ON mr.name = mri.parent
			    WHERE mr.docstatus < 2 AND mri.item_code = %(item)s
			      AND mr.production_order = %(wo)s {cond}""",
			{"item": item_code, "wo": work_order, "exclude_mr": exclude_mr},
		)
		prev_requested = flt(prev[0][0]) if prev else 0.0

	balance = max(0.0, required - issued)
	return {
		"warehouse": store,
		"available": available,
		"required": required,
		"prev_requested": prev_requested,
		"issued": issued,
		"balance_to_issue": balance,
		"final_available": available - balance,
	}
