# End-to-end smoke test of the Lumirise Focus-9 flow on standard ERPNext + the
# custom screens. Creates two Sales Orders that share common parts, plans each
# (Post -> Work Order + Indent), consolidates the indents into POs, then drives
# Vendor PDI -> Logistics -> IQC -> GRN, manufacture, Customer PDI, Dispatch --
# verifying the IQC gate (blocks GRN) and Customer PDI gate (blocks Dispatch).
#
# Run:     bench --site site.com execute lumirise_custom.demo.smoke_test.run
# Cleanup: bench --site site.com execute lumirise_custom.demo.smoke_test.cleanup

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, nowdate, flt

from lumirise_custom.lumirise_custom.doctype.material_planning.material_planning import compute_plan
from lumirise_custom.lumirise_custom.doctype.indent.indent import get_consolidated_po_items
from lumirise_custom import chain

COMPANY = "Lumirise"
STORES = "Stores - L"
FG_STORE = "Finished Goods - L"


def _approved_so(customer, item, qty, rate):
	so = frappe.get_doc({
		"doctype": "Sales Order", "company": COMPANY, "customer": customer,
		"transaction_date": nowdate(), "delivery_date": add_days(nowdate(), 21),
		"order_type": "Sales",
		"items": [{
			"item_code": item, "qty": qty, "rate": rate,
			"delivery_date": add_days(nowdate(), 21), "warehouse": FG_STORE,
		}],
	})
	so.insert(ignore_permissions=True)
	apply_workflow(so, "Coordinator Approve")
	apply_workflow(so, "Head of Sales Approve")
	return so.name


def _plan(sales_orders):
	data = compute_plan(sales_orders)
	mp = frappe.get_doc({"doctype": "Material Planning", "planning_date": nowdate(),
						 "branch": COMPANY, "due_date": add_days(nowdate(), 30)})
	for r in data["fg_plan"]:
		mp.append("fg_plan", r)
	for r in data["components"]:
		mp.append("components", r)
	mp.insert(ignore_permissions=True)
	# Material Planning Approval workflow governs submit: walk the maker->checker
	# transitions (Submit for Approval -> Planning Manager Approve) so the smoke test
	# Posts the plan (== Work Orders + Indent) non-interactively. The seed runner needs
	# both workflow roles for get_transitions() to offer the actions.
	from frappe.model.workflow import apply_workflow
	frappe.get_doc("User", frappe.session.user).add_roles("Planning User", "Planning Manager")
	mp = apply_workflow(mp, "Submit for Approval")
	mp = apply_workflow(mp, "Planning Manager Approve")
	return mp.reload()


def _inbound_chain(po):
	"""Vendor PDI -> Logistics -> IQC -> GRN for one PO (full accept)."""
	po_doc = frappe.get_doc("Purchase Order", po)
	if po_doc.docstatus == 0:
		po_doc.submit()

	# use the exact chain mappers the UI "Create" buttons call
	vpdi = chain.make_vendor_pdi(po)
	vpdi.insert(ignore_permissions=True); vpdi.submit()

	log = chain.make_inbound_logistics(vpdi.name)
	log.lr_number = "LR-" + po[-4:]; log.vehicle_no = "TS09AB1234"
	log.insert(ignore_permissions=True); log.submit()

	# --- gate check: GRN must be BLOCKED before IQC (savepoint so only this
	#     attempt rolls back, not the Vendor PDI / Logistics above) ---
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
	frappe.db.savepoint("before_grn_gate")
	blocked = False
	try:
		pr = make_purchase_receipt(po)
		for it in pr.items:
			it.warehouse = STORES
		pr.insert(ignore_permissions=True)
		pr.submit()
	except frappe.ValidationError:
		blocked = True
		frappe.db.rollback(save_point="before_grn_gate")
	print(f"    IQC gate blocked GRN before IQC for {po}: {blocked}")

	iqc = chain.make_iqc(log.name)
	iqc.sampling_plan = "AQL 1.0"
	iqc.insert(ignore_permissions=True); iqc.submit()

	# now GRN should go through
	pr2 = chain.make_grn(iqc.name)
	pr2.insert(ignore_permissions=True); pr2.submit()
	print(f"    GRN {pr2.name} posted after IQC {iqc.name}")
	return pr2.name


def _manufacture(wo_name, qty):
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry
	for purpose in ("Material Transfer for Manufacture", "Manufacture"):
		se = frappe.get_doc(make_stock_entry(wo_name, purpose, qty))
		se.insert(ignore_permissions=True); se.submit()
	print(f"    Manufactured {qty} on {wo_name}")


def _customer_pdi(so, item, qty, source_wh):
	"""Drive the rebuilt two-leg, store-authorized Customer PDI to a passed,
	SUBMITTED state — the only state that opens the dispatch gate. The document
	stays Draft through the flow and submits only on authorize_return (a stray
	native Submit is blocked). Admin carries the System Manager role, which
	satisfies the store-authority check. source_wh is the warehouse the finished
	goods actually sit in (the Work Order's fg_warehouse), so the FG -> PDI -> FG
	legs draw from and return to the right store and dispatch still finds the qty."""
	from lumirise_custom.lumirise_custom.doctype.customer_pdi import customer_pdi as cpdi_api
	cpdi = frappe.get_doc({
		"doctype": "Customer PDI",
		"sales_order": so,
		"inspection_date": nowdate(),
		"source_warehouse": source_wh,
		"items": [{"fg_item": item, "qty": qty}],
	})
	cpdi.insert(ignore_permissions=True)
	cpdi_api.send_for_authorization(cpdi.name)   # Draft -> Pending Store Authorization
	cpdi_api.authorize_send(cpdi.name)           # Store authorizes -> FG -> PDI transfer (At PDI)
	cpdi_api.complete_inspection(cpdi.name)      # untouched rows => full pass, sign-off Pass
	cpdi_api.authorize_return(cpdi.name)         # PDI -> FG return + submit (Pass) -> opens gate
	return cpdi.name


def _dispatch(so, qty, warehouse):
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
	dn = frappe.get_doc(make_delivery_note(so))
	for it in dn.items:
		it.qty = min(flt(it.qty), qty)
		it.warehouse = warehouse
	dn.insert(ignore_permissions=True)
	return dn


def run():
	so1 = _approved_so("Starlight Electricals", "LED-PANEL-24W", 3000, 410)
	so2 = _approved_so("Bright Lights Distributors", "LED-PANEL-36W", 2000, 595)
	print(f"SO1={so1}  SO2={so2}")

	mp1 = _plan([so1]); mp2 = _plan([so2])
	print(f"MP1={mp1.name} WO=[{mp1.created_work_orders}] Indent={mp1.created_indent}")
	print(f"MP2={mp2.name} WO=[{mp2.created_work_orders}] Indent={mp2.created_indent}")
	for c in mp2.components:
		if c.component_item in ("SCREW-M3", "DRIVER-24W"):
			print(f"  MP2 {c.component_item}: req={c.required_qty} avail={c.rm_available} "
				  f"blocked={c.blocked_for_other_so} usable={c.available_after_blocking} "
				  f"to_order={c.to_be_ordered}")

	data = get_consolidated_po_items([mp1.created_indent, mp2.created_indent])
	print("Consolidated PO items:", [(i["item_code"], i["qty"]) for i in data["items"]])
	print("Reconciliation:", data["reconciliation"])

	# Mimic the buyer: the UI routes to ONE fresh PO pre-filled with these items
	# and no supplier; the buyer picks the supplier on screen. Here we build that
	# single PO and submit it (which flags the source indents Ordered on_submit).
	po = frappe.get_doc({
		"doctype": "Purchase Order",
		"supplier": "Shenzhen LED Imports",
		"company": COMPANY,
		"schedule_date": add_days(nowdate(), 15),
		"buying_price_list": "Standard Buying",
		"lr_indent_refs": ", ".join(data["indents"]),
		"items": [{
			"item_code": i["item_code"], "qty": i["qty"], "uom": i["uom"],
			"schedule_date": i["schedule_date"], "warehouse": i["warehouse"],
		} for i in data["items"]],
	})
	po.insert(ignore_permissions=True)
	print(f"PO={po.name} (single consolidated PO, supplier set by buyer)")

	print("Inbound chain:")
	_inbound_chain(po.name)
	print("Indents Ordered after PO submit:",
		  [frappe.db.get_value("Indent", n, "workflow_state") for n in data["indents"]])

	wo1 = mp1.created_work_orders.split(", ")[0]
	_manufacture(wo1, 3000)
	# Manufacture lands FG in the Work Order's fg_warehouse (line-aware flow), which
	# may not be FG_STORE — pin the PDI + dispatch to wherever the goods actually are.
	fg_wh = frappe.db.get_value("Work Order", wo1, "fg_warehouse") or FG_STORE
	print("FG stock LED-PANEL-24W:",
		  flt(frappe.db.get_value("Bin", {"item_code": "LED-PANEL-24W", "warehouse": fg_wh}, "actual_qty")),
		  "in", fg_wh)

	# --- gate check: Dispatch BLOCKED before Customer PDI ---
	frappe.db.savepoint("before_dispatch_gate")
	blocked = False
	try:
		dn = _dispatch(so1, 3000, fg_wh)
		dn.submit()
	except frappe.ValidationError:
		blocked = True; frappe.db.rollback(save_point="before_dispatch_gate")
	print(f"  Customer-PDI gate blocked Dispatch before PDI: {blocked}")

	cpdi = _customer_pdi(so1, "LED-PANEL-24W", 3000, fg_wh)
	dn2 = _dispatch(so1, 3000, fg_wh)
	dn2.submit()
	print(f"  Customer PDI {cpdi} passed -> Dispatch {dn2.name} submitted")

	frappe.db.commit()
	print("SMOKE RUN OK")


def cleanup():
	"""Roll back ALL transactional docs (keeps masters + opening stock) so the
	bench is clean for filming or a fresh smoke run."""
	order = [
		"Payment Entry", "Sales Invoice", "Delivery Note", "Customer PDI",
		"Purchase Receipt", "Purchase Invoice", "IQC", "Inbound Logistics",
		"Vendor PDI", "Purchase Order", "Indent",
		"Stock Entry", "Work Order", "Production Plan", "Material Planning", "Sales Order",
	]
	for dt in order:
		for name in frappe.get_all(dt, pluck="name"):
			if dt == "Stock Entry" and frappe.db.get_value("Stock Entry", name, "remarks") == "LUMIRISE_PANEL_OPENING":
				continue  # keep the opening-stock entry
			try:
				doc = frappe.get_doc(dt, name)
				if doc.docstatus == 1:
					doc.cancel()
				frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
			except Exception as e:
				print(f"  could not remove {dt} {name}: {e}")
	frappe.db.commit()
	print("Cleanup done — masters + opening stock retained.")
