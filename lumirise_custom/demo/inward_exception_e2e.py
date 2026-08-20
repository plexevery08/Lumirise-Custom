"""Create one retained transport-damage / IQC-fail inward audit trail."""

import frappe
from frappe.utils import add_days, nowdate

from lumirise_custom import chain, inward_process
from lumirise_custom.lumirise_custom.doctype.inbound_logistics import inbound_logistics
from lumirise_custom.lumirise_custom.doctype.iqc import iqc as iqc_api


RUN_ID = "20260810"
ITEM_CODE = f"SYN-RM-INWARD-EXC-{RUN_ID}"
PO_TITLE = f"INWARD_EXCEPTION_E2E_{RUN_ID}"


def _ensure_item():
	if frappe.db.exists("Item", ITEM_CODE):
		return ITEM_CODE
	return frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": ITEM_CODE,
			"item_name": "Synthetic Transport-damaged RM",
			"item_group": "Raw Material",
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"is_sales_item": 0,
			"is_purchase_item": 1,
		}
	).insert(ignore_permissions=True).name


def run():
	frappe.flags.ignore_permissions = True
	existing_po = frappe.db.get_value(
		"Purchase Order", {"title": PO_TITLE, "docstatus": 1}, "name"
	)
	if existing_po:
		log = frappe.db.get_value(
			"Inbound Logistics", {"purchase_order": existing_po, "docstatus": 1}, "name"
		)
		return {
			"state": "already existed",
			"purchase_order": existing_po,
			"inbound_logistics": log,
			"inward_stage": frappe.db.get_value("Inbound Logistics", log, "inward_stage"),
		}

	item_code = _ensure_item()
	po = frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"supplier": "Shenzhen LED Imports",
			"company": "Lumirise",
			"transaction_date": nowdate(),
			"schedule_date": add_days(nowdate(), 7),
			"title": PO_TITLE,
			"items": [
				{
					"item_code": item_code,
					"qty": 6,
					"rate": 30,
					"schedule_date": add_days(nowdate(), 7),
					"warehouse": "Stores - L",
				}
			],
		}
	)
	po.insert(ignore_permissions=True)
	po.submit()

	vpdi = chain.make_vendor_pdi(po.name)
	vpdi.insert(ignore_permissions=True)
	vpdi.submit()
	log = chain.make_inbound_logistics(vpdi.name)
	log.lr_number = f"SYN-DAMAGE-LR-{RUN_ID}"
	log.vehicle_no = "SYN-DAMAGE-TRUCK"
	log.transporter = "Synthetic Transporter"
	log.no_of_boxes = 1
	log.receiving_warehouse = "Stock-In - L"
	log.insert(ignore_permissions=True)
	log.submit()

	inbound_logistics.mark_in_transit(log.name)
	inward_process.register_vehicle_arrival(log.name)
	inward_process.approve_vehicle_entry(log.name)
	inward_process.verify_gate_entry(log.name, f"DAMAGE-GATE-{RUN_ID}")
	inward_process.verify_documents(
		log.name,
		invoice_verified=1,
		packing_list_matched=1,
		waybill_verified=1,
		documents_forwarded_to_manager=1,
	)
	created = inward_process.raise_iqc_task(log.name)
	inward_process.start_unloading(log.name)
	inward_process.complete_unloading(log.name)

	log.reload()
	exception = log.append(
		"inward_exceptions",
		{
			"exception_type": "Transport Damage",
			"item_code": item_code,
			"expected_qty": 6,
			"actual_qty": 6,
			"exception_qty": 6,
			"status": "Open",
			"required_action": "Transport Claim",
			"evidence": f"/private/files/SYN-TRANSPORT-DAMAGE-{RUN_ID}.jpg",
			"remarks": "Synthetic carton damage used to verify the exception branch.",
		},
	)
	log.save(ignore_permissions=True)
	inward_process.record_physical_verification(
		log.name, "Transport Damage", "All six pieces isolated in the rejection area"
	)
	inward_process.verify_invoice_price(log.name)

	iqc = frappe.get_doc("IQC", created["iqc"])
	iqc_api.start_testing(iqc.name)
	iqc.reload()
	for row in iqc.items:
		row.received_qty = 6
		row.accepted_qty = 0
		row.rejected_qty = 6
		row.under_test_qty = 0
		row.on_hold_qty = 0
		row.reject_reason = "Transport damage"
		row.disposition = "Return to Vendor"
	iqc.save(ignore_permissions=True)
	iqc_api.record_result(iqc.name)
	iqc.reload()
	iqc.submit()

	storage_blocked = False
	blocked_message = None
	try:
		inward_process.authorize_storage(log.name, "RM Rack A-01 - L")
	except frappe.ValidationError as error:
		storage_blocked = True
		blocked_message = str(error)

	log.reload()
	exception = log.inward_exceptions[0]
	exception_task = exception.purchase_task
	inward_process.resolve_exception(exception.name, f"TRANSPORT-CLAIM-{RUN_ID}")
	frappe.db.commit()
	return {
		"purchase_order": po.name,
		"inbound_logistics": log.name,
		"iqc": iqc.name,
		"iqc_status": frappe.db.get_value("IQC", iqc.name, "status"),
		"inward_stage": frappe.db.get_value("Inbound Logistics", log.name, "inward_stage"),
		"iqc_task": created["task"],
		"exception": exception.name,
		"exception_task": exception_task,
		"exception_status": frappe.db.get_value(
			"Inbound Process Exception", exception.name, "status"
		),
		"storage_blocked": storage_blocked,
		"blocked_message": blocked_message,
		"purchase_receipt": None,
	}
