"""Stores process — standard Pick List & Put-away on native ERPNext.

PICK LIST (the picker's list with rack/bin locations):
  * make_work_order_pick_list -> native Pick List for a Work Order's material
    issue, auto-filled with bin locations via set_item_locations().
  * make_delivery_pick_list  -> native Pick List (Delivery) for a Sales Order.
  Either way, a "pick & stage" task is raised for the relevant store.

PUT-AWAY (inbound):
  Native Putaway Rules distribute received goods into rack/bin warehouses on the
  GRN ("Apply Putaway Rule"). The GRN put-away task (task_engine) tells stores to
  confirm the rack/bin. Nothing is hard-coded — warehouses come from the document
  or Lumirise Operations Settings (config.py).
"""

import frappe
from frappe import _
from frappe.utils import flt

from lumirise_custom import defaults as config
from lumirise_custom.task_engine import create_task


@frappe.whitelist()
def make_work_order_pick_list(work_order):
	"""Native Pick List (with bin locations) to pick the BOM materials for a
	Work Order's material issue."""
	frappe.has_permission("Work Order", "read", work_order, throw=True)
	wo = frappe.get_doc("Work Order", work_order)
	if wo.docstatus != 1:
		frappe.throw(_("Work Order {0} must be submitted first.").format(work_order))
	for_qty = flt(wo.qty) - flt(wo.material_transferred_for_manufacturing)
	if for_qty <= 0:
		frappe.throw(_("Nothing left to pick — all material for this Work Order is already issued."))

	pl = frappe.get_doc(
		{
			"doctype": "Pick List",
			"purpose": "Material Transfer for Manufacture",
			"work_order": work_order,
			"for_qty": for_qty,
			"company": wo.company,
		}
	)
	pl.set_item_locations()  # native: pulls WO items + their rack/bin locations
	pl.flags.ignore_permissions = True
	pl.insert(ignore_permissions=True)
	return {"pick_list": pl.name}


@frappe.whitelist()
def make_delivery_pick_list(sales_order):
	"""Native Pick List (Delivery) to pick finished goods for a Sales Order."""
	frappe.has_permission("Sales Order", "read", sales_order, throw=True)
	so = frappe.get_doc("Sales Order", sales_order)
	if so.docstatus != 1:
		frappe.throw(_("Sales Order {0} must be submitted first.").format(sales_order))

	pl = frappe.get_doc(
		{
			"doctype": "Pick List",
			"purpose": "Delivery",
			"company": so.company,
			"locations": [
				{
					"item_code": soi.item_code,
					"qty": flt(soi.qty) - flt(soi.delivered_qty),
					"stock_qty": flt(soi.qty) - flt(soi.delivered_qty),
					"uom": soi.uom,
					"stock_uom": soi.stock_uom,
					"conversion_factor": soi.conversion_factor or 1,
					"sales_order": sales_order,
					"sales_order_item": soi.name,
				}
				for soi in so.items
				if (flt(soi.qty) - flt(soi.delivered_qty)) > 0
			],
		}
	)
	if not pl.locations:
		frappe.throw(_("Nothing left to pick — the order is fully delivered."))
	pl.set_item_locations()  # native: fill rack/bin locations
	pl.flags.ignore_permissions = True
	pl.insert(ignore_permissions=True)
	return {"pick_list": pl.name}


def on_pick_list_insert(doc, method=None):
	"""Pick List created -> raise a 'pick & stage' task for the right store."""
	try:
		if not config.flag("enable_pick_list_task", True):
			return
		if doc.get("purpose") == "Delivery":
			dept, what = "FG Stores - Dispatch", "finished goods for dispatch"
		else:
			dept, what = "Stores - RM", "raw material for the line"
		create_task(
			title=f"Pick {what} — {doc.name}",
			department=dept,
			task_type="Handoff",
			priority="Medium",
			reference_doctype="Pick List",
			reference_name=doc.name,
			description=(
				f"Pick List {doc.name} ({doc.get('purpose')}) is ready. Pick each item "
				f"from its rack/bin location shown on the list and stage it."
			),
			source_event="pick_list",
			dedup=False,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Stores: on_pick_list_insert failed")
