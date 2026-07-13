"""End-to-end smoke test for the Sales Platform rebuild (plan step 10).

Exercises the whole chain on the local bench:

    RM item landed cost (RMB -> INR + duty)
      -> costed Parent BOM (layered cost + MOQ slab prices)
      -> pricing masters (mono box / master box / transport / credit)
      -> Price Sheet (rows generated server-side)
      -> submit -> approval lines -> approve()
      -> ERPNext Quotation at the negotiated customer price

Run with:
    bench --site site.com execute lumirise_custom.demo.sales_smoke_test.run

Idempotent: deletes and recreates everything under the SPTEST- prefix.
"""

import frappe
from frappe.utils import flt

PREFIX = "SPTEST"
RM_ITEM = f"{PREFIX}-LED-DRIVER"
FG_ITEM = f"{PREFIX}-LED-BULB-9W"
CUSTOMER = f"{PREFIX} Customer"
FINISH_UV = "UV DRIPOFF SPOT"
FINISH_MATT = "MATT LAMINATION"
CASELOT = 50

results = []


def check(label, ok, detail=""):
	results.append((label, bool(ok), detail))
	print(("PASS" if ok else "FAIL"), "-", label, ("- " + str(detail)) if detail else "")


def cleanup():
	from lumirise_custom import defaults as config
	config.assert_destructive_seeder_allowed("sales_smoke_test.cleanup (deletes Price Sheets/Quotations/BOMs/Items)")
	for sheet in frappe.get_all("Price Sheet", filters={"customer": CUSTOMER}, pluck="name"):
		doc = frappe.get_doc("Price Sheet", sheet)
		if doc.quotation and frappe.db.exists("Quotation", doc.quotation):
			q = frappe.get_doc("Quotation", doc.quotation)
			if q.docstatus == 1:
				q.cancel()
			frappe.delete_doc("Quotation", q.name, force=True)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Price Sheet", sheet, force=True)

	for dt in ("Lumirise Base Price", "Mono Box Pricing", "Master Box Pricing",
			"Transport Pricing"):
		for name in frappe.get_all(dt, filters={"item": FG_ITEM}, pluck="name"):
			frappe.delete_doc(dt, name, force=True)

	for bom in frappe.get_all("BOM", filters={"item": FG_ITEM}, pluck="name"):
		doc = frappe.get_doc("BOM", bom)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("BOM", bom, force=True)

	for item in (FG_ITEM, RM_ITEM):
		if frappe.db.exists("Item", item):
			frappe.delete_doc("Item", item, force=True)


def ensure_masters():
	group = (frappe.db.exists("Item Group", "Products")
		or frappe.db.exists("Item Group", "All Item Groups"))

	# RM with landed-cost inputs: 10 RMB * 12 = 120 INR + 10% duty = 132.0
	rm = frappe.new_doc("Item")
	rm.item_code = RM_ITEM
	rm.item_name = RM_ITEM
	rm.item_group = group
	rm.stock_uom = "Nos"
	rm.gst_hsn_code = "85391000"
	rm.custom_price_in_rmb = 10
	rm.custom_rmb_to_inr_rate = 12
	rm.custom_custom_duty = 10
	rm.insert(ignore_permissions=True)
	check("Item landed cost computed", flt(rm.valuation_rate) == 132.0,
		f"valuation_rate={rm.valuation_rate}")

	fg = frappe.new_doc("Item")
	fg.item_code = FG_ITEM
	fg.item_name = FG_ITEM
	fg.item_group = group
	fg.stock_uom = "Nos"
	fg.gst_hsn_code = "85391000"
	fg.insert(ignore_permissions=True)

	for finish in (FINISH_UV, FINISH_MATT):
		if not frappe.db.exists("Box Finish", finish):
			frappe.get_doc({"doctype": "Box Finish", "finish_name": finish}).insert(
				ignore_permissions=True)

	for moq, selling, profit in ((1000, 2.5, 0.9), (3000, 2.2, 0.8),
			(6000, 2.0, 0.7), (10000, 1.8, 0.6)):
		for finish in (FINISH_UV, FINISH_MATT):
			frappe.get_doc({
				"doctype": "Mono Box Pricing",
				"item": FG_ITEM, "box_finish": finish, "moq": str(moq),
				"purchase_price": selling - 0.5, "selling_price": selling,
				"profit_price": profit,
			}).insert(ignore_permissions=True)

	frappe.get_doc({
		"doctype": "Master Box Pricing",
		"item": FG_ITEM, "box_finish": FINISH_UV, "caselot": CASELOT,
		"purchase_price": 30.0, "price_per_unit": 0.6,
	}).insert(ignore_permissions=True)

	frappe.get_doc({
		"doctype": "Transport Pricing",
		"item": FG_ITEM, "transport_type": "Public", "transport_zone": "South",
		"cost_per_unit": 1.25,
	}).insert(ignore_permissions=True)

	if not frappe.db.exists("Customer", CUSTOMER):
		frappe.get_doc({
			"doctype": "Customer", "customer_name": CUSTOMER,
			"customer_group": "Commercial", "territory": "India",
		}).insert(ignore_permissions=True)


def make_costed_bom():
	company = frappe.defaults.get_global_default("company")
	bom = frappe.new_doc("BOM")
	bom.item = FG_ITEM
	bom.company = company
	bom.quantity = 1
	bom.custom_bom_type = "Parent BOM"
	bom.custom_1k_moq_percentage = 12
	bom.custom_3k_moq_percentage = 10
	bom.custom_6k_moq_percentage = 8
	bom.custom_10k_moq_percentage = 6
	bom.append("items", {"item_code": RM_ITEM, "qty": 1, "uom": "Nos", "rate": 0})
	bom.insert(ignore_permissions=True)
	bom.submit()
	bom.reload()

	# 132 raw + no layers -> bom_cost 132; 3k slab = 132 * 1.10 = 145.2
	check("BOM cost rolled up", flt(bom.custom_bom_cost) == 132.0,
		f"custom_bom_cost={bom.custom_bom_cost}")
	check("BOM 3k MOQ price", flt(bom.custom_3k_moq_price) == 145.2,
		f"custom_3k_moq_price={bom.custom_3k_moq_price}")
	return bom


def make_price_sheet():
	sheet = frappe.new_doc("Price Sheet")
	sheet.customer = CUSTOMER
	sheet.delivery_type = "Transport"
	sheet.transport_type = "Public"
	sheet.transport_zone = "South"
	sheet.payment_type = "Credit"
	sheet.credit_days = 30
	sheet.listening_percentage = 2
	sheet.master_box_finish = FINISH_UV
	sheet.master_box_caselots = str(CASELOT)
	sheet.append("products", {"item": FG_ITEM})
	for finish in (FINISH_UV, FINISH_MATT):
		sheet.append("mono_box_finishes", {"box_finish": finish})
	sheet.insert(ignore_permissions=True)

	# 4 tiers x (1 baseline + 2 finishes) x 1 caselot = 12 rows
	check("Price sheet rows generated", len(sheet.rows) == 12,
		f"rows={len(sheet.rows)}")
	check("LQ naming series", sheet.name.startswith("LQ-"), sheet.name)

	row = next((r for r in sheet.rows
		if r.box_finish == FINISH_UV and r.moq == 3000), None)
	# base 145.2 + mono 2.2 + master 0.6 + transport 1.25 = 149.25
	# credit 1% -> 1.4925 -> r3 = 1.493 (banker-safe flt) -> total 150.743
	expected_subtotal = 145.2 + 2.2 + 0.6 + 1.25
	expected_credit = flt(expected_subtotal * 0.01, 3)
	expected_total = flt(expected_subtotal + expected_credit, 3)
	check("Row math (3k, UV)", row and flt(row.total) == expected_total,
		f"total={row.total if row else None} expected={expected_total} "
		f"source={row.price_source if row else None}")
	check("Base price from BOM", row and row.price_source == "BOM",
		row.price_source if row else None)
	check("Listening applied to final_total",
		row and flt(row.final_total) == flt(flt(row.total) * 1.02, 3),
		f"final_total={row.final_total if row else None}")

	sheet.submit()
	sheet.reload()
	check("Submitted -> Pending Approval", sheet.status == "Pending Approval",
		sheet.status)
	return sheet


def approve(sheet):
	sheet.populate_approval_items()
	sheet.reload()
	line = sheet.approval_items[0]
	line.customer_agreed_qty = 3500          # -> selected_moq 3000
	line.customer_price = 152.0
	sheet.save(ignore_permissions=True)

	quotation_name = sheet.approve()
	sheet.reload()
	line = sheet.approval_items[0]

	check("Approved", sheet.status == "Approved", sheet.status)
	check("Selected MOQ derived from qty", line.selected_moq == 3000,
		line.selected_moq)

	# calculated 150.743 + listening 2% (3.015) = 153.758; variance = 152 - 153.758
	expected_listening = flt(flt(line.calculated_price) * 2 / 100.0, 3)
	expected_variance = flt(152.0 - (flt(line.calculated_price) + expected_listening), 3)
	check("Listening amount", flt(line.listening_amount) == expected_listening,
		f"{line.listening_amount} vs {expected_listening}")
	check("Variance", flt(line.variance) == expected_variance,
		f"{line.variance} vs {expected_variance} (calc={line.calculated_price})")

	q = frappe.get_doc("Quotation", quotation_name)
	check("Quotation created", bool(q), quotation_name)
	check("Quotation rate = customer price", flt(q.items[0].rate) == 152.0,
		q.items[0].rate)
	check("Quotation qty = agreed qty", flt(q.items[0].qty) == 3500,
		q.items[0].qty)
	check("Quotation back-reference", q.get("custom_price_sheet") == sheet.name,
		q.get("custom_price_sheet"))


def run():
	from lumirise_custom import defaults as config
	config.assert_destructive_seeder_allowed("sales_smoke_test.run")
	frappe.flags.in_test = False
	cleanup()
	ensure_masters()
	make_costed_bom()
	sheet = make_price_sheet()
	approve(sheet)
	frappe.db.commit()

	failed = [r for r in results if not r[1]]
	print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
	if failed:
		raise frappe.ValidationError(
			"Smoke test failures: " + ", ".join(r[0] for r in failed))
	return "OK"
