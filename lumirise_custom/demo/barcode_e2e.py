"""Create and execute one safe synthetic RM barcode inward-to-shop-floor run.

Run from the bench root:
    bench --site site.com execute lumirise_custom.demo.barcode_e2e.run

The run uses a uniquely named synthetic Item and leaves the submitted records in
place for screen-based walkthrough and audit. It does not delete or alter
existing business records.
"""

import json

import frappe
from frappe.utils import add_days, nowdate

from lumirise_custom import chain
from lumirise_custom.lumirise_custom.doctype.inbound_logistics import inbound_logistics
from lumirise_custom.lumirise_custom.doctype.rm_package import rm_package


COMPANY = "Lumirise"
SUPPLIER = "Shenzhen LED Imports"
RM_STORE = "Stores - L"
RECEIVING = "Shopfloor Stock in Area - L"
PUTAWAY = "RM-R01-Bin-A - L"
SHOP_FLOOR = "Shop Floor - L"
RUN_ID = "20260808"
ITEM_CODE = f"SYN-RM-BARCODE-{RUN_ID}"
SUPPLIER_LOT = f"SYN-LOT-{RUN_ID}"


def _ensure_item():

	if frappe.db.exists("Item", ITEM_CODE):
		return ITEM_CODE
	item = frappe.get_doc({
		"doctype": "Item",
		"item_code": ITEM_CODE,
		"item_name": "Synthetic RM Barcode Demo 24W",
		"item_group": "Raw Material",
		"stock_uom": "Nos",
		"is_stock_item": 1,
		"is_sales_item": 0,
		"is_purchase_item": 1,
		"has_batch_no": 1,
		"include_item_in_manufacturing": 1,
	})
	item.insert(ignore_permissions=True)
	return item.name


def _submitted(doctype, filters):
	return frappe.db.get_value(doctype, {**filters, "docstatus": 1}, "name")


def run():
	frappe.flags.ignore_permissions = True
	item_code = _ensure_item()
	po_name = _submitted("Purchase Order", {"title": f"BARCODE_E2E_{RUN_ID}"})

	if po_name:
		po = frappe.get_doc("Purchase Order", po_name)
		vpdi_name = frappe.db.get_value("Vendor PDI", {"purchase_order": po.name, "docstatus": 1}, "name")
		log_name = frappe.db.get_value("Inbound Logistics", {"purchase_order": po.name, "docstatus": 1}, "name")
		pkg_name = frappe.db.get_value("RM Package", {"supplier_lot": SUPPLIER_LOT}, "name")
		return _report(po.name, vpdi_name, log_name, pkg_name, "already existed")

	po = frappe.get_doc({
		"doctype": "Purchase Order",
		"supplier": SUPPLIER,
		"company": COMPANY,
		"transaction_date": nowdate(),
		"schedule_date": add_days(nowdate(), 7),
		"buying_price_list": "Standard Buying",
		"title": f"BARCODE_E2E_{RUN_ID}",
		"items": [{
			"item_code": item_code,
			"qty": 24,
			"rate": 25,
			"schedule_date": add_days(nowdate(), 7),
			"warehouse": RM_STORE,
		}],
	})
	po.insert(ignore_permissions=True)
	po.submit()

	vpdi = chain.make_vendor_pdi(po.name)
	vpdi.insert(ignore_permissions=True)
	vpdi.submit()

	log = chain.make_inbound_logistics(vpdi.name)
	log.lr_number = f"SYN-LR-{RUN_ID}"
	log.lr_date = nowdate()
	log.vehicle_no = "SYN-TRUCK-001"
	log.transporter = "Synthetic Transporter"
	log.no_of_boxes = 1
	log.receiving_warehouse = RECEIVING
	log.insert(ignore_permissions=True)
	log.submit()
	inbound_logistics.verify_documents(log.name)
	inbound_logistics.approve_gate(log.name)
	inbound_logistics.mark_in_transit(log.name)
	inbound_logistics.mark_reached(log.name)

	pkg = rm_package.create_from_inbound(
		log.name, item_code, 24, supplier_lot=SUPPLIER_LOT,
		current_warehouse=RECEIVING,
	)

	iqc = chain.make_iqc(log.name)
	iqc.sampling_plan = "Synthetic 100% check"
	for row in iqc.items:
		row.received_qty = 24
		row.accepted_qty = 24
		row.rejected_qty = 0
	iqc.insert(ignore_permissions=True)
	iqc.submit()

	pr = chain.make_grn(iqc.name)
	# ERPNext requires the native batch on the Purchase Receipt line for a
	# batch-tracked item. The package/IQC already identify the authoritative
	# batch; copy it onto the standard GRN before stock is posted.
	for row in pr.items:
		if row.item_code == item_code:
			row.batch_no = pkg.batch_no
	pr.insert(ignore_permissions=True)
	pr.submit()
	pkg.reload()
	if pkg.status != "Available":
		rm_package.release_after_grn(pkg.name, pr.name, iqc.name)
	pkg.reload()

	scan_before = rm_package.scan_package(pkg.package_barcode)
	putaway = rm_package.put_away(pkg.package_barcode, PUTAWAY)
	pkg.reload()
	scan_after_putaway = rm_package.scan_package(pkg.package_barcode)

	issue = frappe.get_doc({
		"doctype": "Stock Entry",
		"stock_entry_type": "Material Issue to Shop Floor",
		"purpose": "Material Transfer",
		"company": COMPANY,
		"from_warehouse": PUTAWAY,
		"to_warehouse": SHOP_FLOOR,
		"lr_scan_package": pkg.package_barcode,
		"lr_scan_source_location": PUTAWAY,
		"custom_narration": f"Synthetic barcode issue {pkg.package_barcode}",
		"items": [{
			"item_code": item_code,
			"qty": 24,
			"uom": "Nos",
			"stock_uom": "Nos",
			"conversion_factor": 1,
			"s_warehouse": PUTAWAY,
			"t_warehouse": SHOP_FLOOR,
			"batch_no": pkg.batch_no,
		}],
	})
	issue.insert(ignore_permissions=True)
	issue.submit()
	pkg.reload()
	scan_after_issue = rm_package.scan_package(pkg.package_barcode)

	frappe.db.commit()
	return {
		"run": RUN_ID,
		"item": item_code,
		"purchase_order": po.name,
		"vendor_pdi": vpdi.name,
		"inbound_logistics": log.name,
		"iqc": iqc.name,
		"purchase_receipt": pr.name,
		"rm_package": pkg.name,
		"barcode": pkg.package_barcode,
		"batch": pkg.batch_no,
		"put_away_stock_entry": putaway["stock_entry"],
		"issue_stock_entry": issue.name,
		"scan_before_putaway": scan_before,
		"scan_after_putaway": scan_after_putaway,
		"scan_after_issue": scan_after_issue,
		"final_package_status": pkg.status,
		"final_package_location": pkg.current_warehouse,
		"iqc_status": frappe.db.get_value("IQC", iqc.name, "status"),
		"purchase_receipt_status": pr.docstatus,
		"stock_qty_in_shop_floor": frappe.db.get_value(
			"Bin", {"item_code": item_code, "warehouse": SHOP_FLOOR}, "actual_qty") or 0,
	}


def _report(po, vpdi, log, pkg, state):
	return {"run": RUN_ID, "state": state, "purchase_order": po, "vendor_pdi": vpdi,
		"inbound_logistics": log, "rm_package": pkg}


if __name__ == "__main__":
	print(json.dumps(run(), indent=2, default=str))
