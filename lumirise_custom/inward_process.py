"""Poster-aligned material inward controls.

This module orchestrates existing documents; it does not create a parallel stock
ledger.  Inbound Logistics owns approvals/evidence, IQC owns quality disposition,
Purchase Receipt owns the GRN, and Stock Entry owns every physical stock move.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from lumirise_custom.action_permissions import (
	require_inward_manager_action,
	require_logistics_action,
	require_purchase_release,
	require_security_action,
	require_stores_acceptance,
)


MATCHED = "Matched"
OPEN_EXCEPTION_STATUSES = (
	"Open",
	"Purchase Notified",
	"Replacement Pending",
	"Debit Note Pending",
	"Transport Claim Pending",
)


def _load_log(docname, permission_type="write"):
	frappe.has_permission("Inbound Logistics", permission_type, docname, throw=True)
	doc = frappe.get_doc("Inbound Logistics", docname)
	if doc.docstatus != 1:
		frappe.throw(_("Submit the Inbound Logistics record before continuing the inward process."))
	return doc


def _update(doc, values):
	frappe.db.set_value(doc.doctype, doc.name, values, update_modified=True)
	for fieldname, value in values.items():
		doc.set(fieldname, value)
	return values


def _task_for(reference_doctype, reference_name, source_event):
	return frappe.db.get_value(
		"Lumirise Task",
		{
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"source_event": source_event,
			"status": ["not in", ["Done", "Cancelled"]],
		},
		"name",
	)


def _create_required_task(**kwargs):
	from lumirise_custom.task_engine import create_task

	task = create_task(**kwargs)
	if not task:
		task = _task_for(
			kwargs.get("reference_doctype"),
			kwargs.get("reference_name"),
			kwargs.get("source_event"),
		)
	if not task:
		frappe.throw(
			_("The mandatory operational task could not be created. Check the Error Log and retry."),
			title=_("Task Creation Failed"),
		)
	return task


def _complete_task(task_name, resolution_note):
	if not task_name or not frappe.db.exists("Lumirise Task", task_name):
		return
	task = frappe.get_doc("Lumirise Task", task_name)
	if task.status in ("Done", "Cancelled"):
		return
	task.status = "Done"
	task.resolution_note = resolution_note
	task.save(ignore_permissions=True)


def _get_iqc(log, require_submitted=False):
	name = log.get("iqc_reference") or frappe.db.get_value(
		"IQC", {"inbound_logistics": log.name, "docstatus": ["<", 2]}, "name"
	)
	if not name:
		frappe.throw(_("Raise the mandatory IQC task before continuing."))
	iqc = frappe.get_doc("IQC", name)
	if require_submitted and iqc.docstatus != 1:
		frappe.throw(_("Submit IQC {0} before authorizing storage or creating the GRN.").format(iqc.name))
	return iqc


def _passed_iqc(log):
	iqc = _get_iqc(log, require_submitted=True)
	if iqc.status not in ("Passed", "Moved to RM"):
		frappe.throw(
			_("IQC {0} is {1}. No IQC pass = no storage and no GRN.").format(iqc.name, iqc.status),
			title=_("IQC Gate"),
		)
	if not any(flt(row.accepted_qty) > 0 for row in iqc.items):
		frappe.throw(_("IQC {0} has no accepted quantity to receive.").format(iqc.name))
	return iqc


def _validate_leaf_warehouse(warehouse, label):
	if not warehouse:
		frappe.throw(_("Select {0}.").format(label))
	row = frappe.db.get_value(
		"Warehouse", warehouse, ["name", "is_group", "lr_location_status"], as_dict=True
	)
	if not row:
		frappe.throw(_("Warehouse {0} does not exist.").format(warehouse))
	if row.is_group:
		frappe.throw(_("{0} must be a leaf rack / bay warehouse.").format(label))
	if row.lr_location_status and row.lr_location_status != "Available":
		frappe.throw(_("{0} is {1} and cannot receive material.").format(warehouse, row.lr_location_status))
	return warehouse


def validate_inbound(doc):
	"""Controller validation for exception integrity and rack allocation."""
	item_codes = {row.item_code for row in (doc.get("items") or [])}
	for row in doc.get("inward_exceptions") or []:
		if row.item_code not in item_codes:
			frappe.throw(_("Exception row {0}: item must belong to this inbound shipment.").format(row.idx))
		if flt(row.exception_qty) <= 0:
			frappe.throw(_("Exception row {0}: Exception Qty must be greater than zero.").format(row.idx))
		if row.exception_type == "Transport Damage" and not row.evidence:
			frappe.throw(_("Exception row {0}: attach transport-damage photos/evidence.").format(row.idx))
		if row.status == "Resolved" and not row.resolution_reference:
			frappe.throw(_("Exception row {0}: add the debit note, replacement, claim, or ERP reference.").format(row.idx))
	if doc.get("rack_warehouse"):
		_validate_leaf_warehouse(doc.rack_warehouse, _("Allocated Rack / Bay"))


@frappe.whitelist()
def register_vehicle_arrival(docname):
	"""Security registers arrival and notifies the Inward Manager."""
	require_security_action()
	doc = _load_log(docname)
	if not doc.vehicle_no:
		frappe.throw(_("Enter the vehicle number before registering arrival."))
	if doc.status not in ("Dispatched", "In Transit", "Reached Warehouse"):
		frappe.throw(_("This consignment cannot be marked as arrived from its current state."))
	when = now_datetime()
	values = {
		"status": "Reached Warehouse",
		"arrival_registered_on": when,
		"arrival_registered_by": frappe.session.user,
		"manager_notified": 1,
		"inward_stage": "Awaiting Gate Approval",
	}
	_update(doc, values)
	_create_required_task(
		title=f"Approve vehicle entry — {doc.name} ({doc.vehicle_no})",
		department="Logistics",
		task_type="Approval",
		priority="High",
		reference_doctype="Inbound Logistics",
		reference_name=doc.name,
		description=(
			f"Vehicle {doc.vehicle_no} has arrived for {doc.name}. Review the consignment and "
			"approve or reject gate entry. No approval = no entry."
		),
		source_event="inbound_gate_approval",
	)
	return values


@frappe.whitelist()
def approve_vehicle_entry(docname):
	"""Inward Manager approval. Security verification remains a separate checkpoint."""
	require_inward_manager_action()
	doc = _load_log(docname)
	if doc.status != "Reached Warehouse" or not doc.get("arrival_registered_on"):
		frappe.throw(_("Security must register the vehicle arrival first."))
	if doc.vehicle_gate_status == "Rejected":
		frappe.throw(_("A rejected vehicle requires a new Inbound Logistics record."))
	when = now_datetime()
	return _update(
		doc,
		{
			"vehicle_gate_status": "Approved",
			"gate_approved_by": frappe.session.user,
			"gate_approved_on": when,
			"inward_stage": "Gate Approved",
		},
	)


@frappe.whitelist()
def reject_vehicle_entry(docname, reason):
	require_inward_manager_action()
	doc = _load_log(docname)
	if not (reason or "").strip():
		frappe.throw(_("Enter the rejection reason."))
	return _update(
		doc,
		{
			"vehicle_gate_status": "Rejected",
			"document_verification_status": "Exception",
			"document_exception": reason.strip(),
			"inward_stage": "Document Exception",
		},
	)


@frappe.whitelist()
def verify_gate_entry(docname, stamp_reference, gate_invoice_attachment=None):
	"""Security confirms the gate stamp/signature after manager approval."""
	require_security_action()
	doc = _load_log(docname)
	if doc.vehicle_gate_status != "Approved":
		frappe.throw(_("The Inward Manager must approve the vehicle before Security permits entry."))
	if not (stamp_reference or "").strip():
		frappe.throw(_("Enter the gate stamp / signature reference."))
	when = now_datetime()
	return _update(
		doc,
		{
			"gate_stamp_reference": stamp_reference.strip(),
			"gate_invoice_attachment": gate_invoice_attachment,
			"gate_verified_by": frappe.session.user,
			"gate_verified_on": when,
			"inward_stage": "Gate Verified",
		},
	)


@frappe.whitelist()
def verify_documents(
	docname,
	invoice_verified=0,
	packing_list_matched=0,
	waybill_verified=0,
	other_documents_received=0,
	documents_forwarded_to_manager=0,
	document_bundle_attachment=None,
	exception=None,
):
	"""Record the exact poster checklist. Failed verification blocks unloading."""
	require_logistics_action()
	doc = _load_log(docname)
	if not doc.get("gate_verified_on"):
		frappe.throw(_("Security must verify the approved gate entry before document handover."))
	if exception:
		return _update(
			doc,
			{
				"document_verification_status": "Exception",
				"document_exception": exception.strip(),
				"inward_stage": "Document Exception",
			},
		)
	checks = {
		_("Invoice Received & Verified"): cint(invoice_verified),
		_("Packing List Received & Matched"): cint(packing_list_matched),
		_("Waybill / LR Received & Verified"): cint(waybill_verified),
		_("Documents Forwarded to Manager"): cint(documents_forwarded_to_manager),
	}
	missing = [label for label, checked in checks.items() if not checked]
	if missing:
		frappe.throw(
			_("Complete the document checklist before unloading: {0}.").format(", ".join(missing)),
			title=_("Document Gate"),
		)
	when = now_datetime()
	return _update(
		doc,
		{
			"invoice_verified": 1,
			"packing_list_matched": 1,
			"waybill_verified": 1,
			"other_documents_received": cint(other_documents_received),
			"documents_forwarded_to_manager": 1,
			"document_bundle_attachment": document_bundle_attachment,
			"document_verification_status": "Verified",
			"document_exception": "",
			"documents_verified_by": frappe.session.user,
			"documents_verified_on": when,
			"inward_stage": "Documents Verified",
		},
	)


def _new_iqc(log):
	doc = frappe.new_doc("IQC")
	doc.inbound_logistics = log.name
	doc.purchase_order = log.purchase_order
	doc.status = "IQC Received"
	for row in log.items:
		doc.append(
			"items",
			{
				"item_code": row.item_code,
				"item_name": row.get("item_name")
				or frappe.db.get_value("Item", row.item_code, "item_name"),
				"received_qty": row.qty,
				"under_test_qty": row.qty,
				"accepted_qty": 0,
				"rejected_qty": 0,
			},
		)
	return doc


@frappe.whitelist()
def raise_iqc_task(docname):
	"""Create the IQC work record and its mandatory task/Bitrix mirror source."""
	require_inward_manager_action()
	doc = _load_log(docname)
	if doc.document_verification_status != "Verified":
		frappe.throw(_("Verified invoice, packing list, and waybill are mandatory before the IQC task."))
	if doc.get("iqc_reference") and frappe.db.exists("IQC", doc.iqc_reference):
		return {"iqc": doc.iqc_reference, "task": doc.get("iqc_task"), "already_exists": 1}
	frappe.has_permission("IQC", "create", throw=True)
	iqc = _new_iqc(doc)
	iqc.insert()
	task = _create_required_task(
		title=f"Perform incoming quality inspection — {iqc.name}",
		department="Quality - PDI/IQC",
		task_type="Handoff",
		priority="High",
		reference_doctype="IQC",
		reference_name=iqc.name,
		description=(
			f"Collect samples at Stock-In for Inbound Logistics {doc.name}, inspect the "
			f"material, and record accepted/rejected quantities against PO {doc.purchase_order}."
		),
		source_event="inbound_iqc_required",
	)
	when = now_datetime()
	_update(
		doc,
		{
			"iqc_reference": iqc.name,
			"iqc_task": task,
			"iqc_task_raised_by": frappe.session.user,
			"iqc_task_raised_on": when,
			"inward_stage": "IQC Task Raised",
		},
	)
	return {"iqc": iqc.name, "task": task}


@frappe.whitelist()
def start_unloading(docname):
	require_logistics_action()
	doc = _load_log(docname)
	if doc.vehicle_gate_status != "Approved" or not doc.get("gate_verified_on"):
		frappe.throw(_("Approved and verified gate entry is mandatory before unloading."))
	if doc.document_verification_status != "Verified":
		frappe.throw(_("No verified documents = no unloading."), title=_("Document Gate"))
	if not doc.get("iqc_task") or not doc.get("iqc_reference"):
		frappe.throw(_("The mandatory IQC task must be raised before unloading."))
	_get_iqc(doc)
	when = now_datetime()
	return _update(
		doc,
		{
			"unloading_status": "In Progress",
			"unloading_started_by": frappe.session.user,
			"unloading_started_on": when,
			"inward_stage": "Unloading In Progress",
		},
	)


@frappe.whitelist()
def complete_unloading(docname):
	require_logistics_action()
	doc = _load_log(docname)
	if doc.get("unloading_status") != "In Progress":
		frappe.throw(_("Start unloading before completing it."))
	when = now_datetime()
	return _update(
		doc,
		{
			"unloading_status": "Completed",
			"unloading_completed_by": frappe.session.user,
			"unloading_completed_on": when,
			"inward_stage": "Physical Verification",
		},
	)


def _exception_task(doc, row):
	source_event = f"inbound_exception_{row.name}"
	task = row.purchase_task or _task_for("Inbound Logistics", doc.name, source_event)
	if task:
		return task
	action = row.required_action or "Purchase disposition"
	return _create_required_task(
		title=f"{row.exception_type} on {doc.name} — {row.item_code}",
		department="Purchase",
		task_type="Defect / Rejection",
		priority="Urgent" if row.exception_type == "Transport Damage" else "High",
		reference_doctype="Inbound Logistics",
		reference_name=doc.name,
		description=(
			f"{row.exception_type}: {row.exception_qty} for item {row.item_code}. "
			f"Required action: {action}. Segregate affected material, complete vendor/transporter "
			"follow-up, and record the debit note, replacement, approval, claim, or ERP update."
		),
		source_event=source_event,
	)


@frappe.whitelist()
def record_physical_verification(docname, status, remarks=None):
	require_logistics_action()
	doc = _load_log(docname)
	if doc.get("unloading_status") != "Completed":
		frappe.throw(_("Complete unloading before recording the physical quantity check."))
	allowed = (
		"Matched",
		"Short Quantity",
		"Excess Quantity",
		"Damaged Material",
		"Transport Damage",
		"Multiple Exceptions",
	)
	if status not in allowed:
		frappe.throw(_("Choose a valid physical verification result."))
	exceptions = list(doc.get("inward_exceptions") or [])
	if status != MATCHED and not exceptions:
		frappe.throw(_("Add at least one Quantity / Damage Exception row before recording this result."))
	for row in exceptions:
		if row.exception_type == "Transport Damage" and not row.evidence:
			frappe.throw(_("Attach photos/evidence for transport damage on row {0}.").format(row.idx))
		task = _exception_task(doc, row)
		frappe.db.set_value(
			"Inbound Process Exception",
			row.name,
			{"purchase_task": task, "status": "Purchase Notified"},
			update_modified=False,
		)
	when = now_datetime()
	return _update(
		doc,
		{
			"physical_verification_status": status,
			"physical_verification_remarks": remarks,
			"physical_verified_by": frappe.session.user,
			"physical_verified_on": when,
		},
	)


@frappe.whitelist()
def verify_invoice_price(docname):
	require_inward_manager_action()
	doc = _load_log(docname)
	if not doc.get("physical_verified_on"):
		frappe.throw(_("Record the packing-list physical quantity check first."))
	when = now_datetime()
	return _update(
		doc,
		{
			"invoice_price_verified": 1,
			"price_verified_by": frappe.session.user,
			"price_verified_on": when,
		},
	)


@frappe.whitelist()
def resolve_exception(exception_name, resolution_reference):
	require_purchase_release()
	row = frappe.get_doc("Inbound Process Exception", exception_name)
	frappe.has_permission("Inbound Logistics", "write", row.parent, throw=True)
	if not (resolution_reference or "").strip():
		frappe.throw(_("Enter the debit note, replacement, claim, approval, or ERP update reference."))
	when = now_datetime()
	frappe.db.set_value(
		"Inbound Process Exception",
		row.name,
		{
			"status": "Resolved",
			"resolution_reference": resolution_reference.strip(),
			"resolved_by": frappe.session.user,
			"resolved_on": when,
		},
	)
	_complete_task(
		row.purchase_task,
		_("Resolved with reference {0}.").format(resolution_reference.strip()),
	)
	return {"status": "Resolved", "resolved_on": when}


@frappe.whitelist()
def authorize_storage(docname, rack_warehouse):
	"""Manager allocates a rack only after the exact IQC has passed."""
	require_inward_manager_action()
	doc = _load_log(docname)
	if doc.get("unloading_status") != "Completed" or not doc.get("physical_verified_on"):
		frappe.throw(_("Complete unloading and physical verification first."))
	if not doc.get("invoice_price_verified"):
		frappe.throw(_("The Inward Manager must verify invoice price against the PO first."))
	iqc = _passed_iqc(doc)
	_validate_leaf_warehouse(rack_warehouse, _("Allocated Rack / Bay"))
	for row in doc.get("inward_exceptions") or []:
		if row.status in OPEN_EXCEPTION_STATUSES and not row.purchase_task:
			frappe.throw(_("Exception row {0} has not been notified to Purchase.").format(row.idx))
	when = now_datetime()
	values = {
		"iqc_reference": iqc.name,
		"rack_warehouse": rack_warehouse,
		"rack_allocated_by": frappe.session.user,
		"rack_allocated_on": when,
		"storage_authorized": 1,
		"storage_authorized_by": frappe.session.user,
		"storage_authorized_on": when,
		"inward_stage": "Storage Authorized",
	}
	_update(doc, values)
	return values


def _logs_for_grn(doc):
	if doc.get("lr_inbound_logistics"):
		return [frappe.get_doc("Inbound Logistics", doc.lr_inbound_logistics)]
	logs = []
	for po in {row.purchase_order for row in doc.items if row.get("purchase_order")}:
		names = frappe.get_all(
			"Inbound Logistics",
			filters={"purchase_order": po, "docstatus": 1, "storage_authorized": 1},
			pluck="name",
		)
		if len(names) > 1:
			frappe.throw(
				_("Multiple authorized inward shipments exist for PO {0}. Select Inbound Logistics on the GRN.").format(po)
			)
		if names:
			logs.append(frappe.get_doc("Inbound Logistics", names[0]))
	return logs


def inward_grn_gate(doc, method=None):
	"""Strict gate for the poster rule: no IQC pass = no GRN."""
	if doc.get("is_subcontracted"):
		return
	for log in _logs_for_grn(doc):
		checks = (
			(log.vehicle_gate_status == "Approved" and log.get("gate_verified_on"), _("gate approval and Security verification")),
			(log.document_verification_status == "Verified", _("document verification")),
			(log.get("iqc_task") and log.get("iqc_reference"), _("mandatory IQC task")),
			(log.get("unloading_status") == "Completed", _("completed unloading")),
			(log.get("physical_verified_on"), _("physical quantity verification")),
			(log.get("invoice_price_verified"), _("invoice-vs-PO price verification")),
			(log.get("storage_authorized"), _("storage authorization and rack allocation")),
		)
		missing = [label for passed, label in checks if not passed]
		if missing:
			frappe.throw(
				_("Inbound {0} is missing: {1}.").format(log.name, ", ".join(missing)),
				title=_("Material Inward Gate"),
			)
		iqc = _passed_iqc(log)
		if doc.get("lr_iqc") and doc.lr_iqc != iqc.name:
			frappe.throw(_("GRN IQC {0} does not match inward IQC {1}.").format(doc.lr_iqc, iqc.name))
		expected, packaged, packages, _unlabelled = package_coverage(log)
		for item, qty in expected.items():
			if abs(qty - packaged.get(item, 0)) > 0.001:
				item_packages = [
					f"{package.name}={flt(package.quantity)}"
					for package in packages
					if package.item_code == item
				]
				package_detail = ", ".join(item_packages) or "none"
				missing_qty = flt(qty) - flt(packaged.get(item, 0))
				frappe.throw(
					_(
						"Inbound {0} / IQC {1}: item {2} has accepted {3}, but its packages "
						"total {4} ({5}). Create {6} more package quantity before submitting "
						"the GRN. Packages from another inbound shipment are not counted."
					).format(
						log.name,
						iqc.name,
						item,
						flt(qty),
						flt(packaged.get(item, 0)),
						package_detail,
						missing_qty,
					),
					title=_("Package Coverage Gate"),
				)
		if not packages:
			frappe.throw(_("Create at least one RM Package / LPN before posting the GRN."))


def on_purchase_receipt_submit(doc, method=None):
	for log in _logs_for_grn(doc):
		frappe.db.set_value(
			"Purchase Receipt",
			doc.name,
			"lr_package_labels_verified",
			0,
			update_modified=False,
		)
		_update(
			log,
			{
				"purchase_receipt": doc.name,
				"inward_stage": "GRN Posted",
			},
		)


def on_purchase_receipt_cancel(doc, method=None):
	for log in _logs_for_grn(doc):
		if log.get("purchase_receipt") == doc.name:
			_update(log, {"purchase_receipt": None, "inward_stage": "Storage Authorized"})


def sync_inbound_from_iqc(doc, method=None):
	if not doc.get("inbound_logistics") or not frappe.db.exists("Inbound Logistics", doc.inbound_logistics):
		return
	stage = {
		"IQC Received": "IQC Task Raised",
		"Testing": "IQC In Progress",
		"Passed": "Physical Verification",
		"On Hold": "IQC In Progress",
		"Rejected": "IQC Failed",
		"Moved to RM": "GRN Posted",
	}.get(doc.status)
	if stage:
		frappe.db.set_value(
			"Inbound Logistics",
			doc.inbound_logistics,
			{"iqc_reference": doc.name, "inward_stage": stage},
			update_modified=True,
		)
	if doc.docstatus == 1 and doc.status in ("Passed", "Rejected", "Moved to RM"):
		task = frappe.db.get_value("Inbound Logistics", doc.inbound_logistics, "iqc_task")
		_complete_task(task, _("IQC {0} submitted with status {1}.").format(doc.name, doc.status))


def _accepted_by_item(log):
	iqc = _passed_iqc(log)
	result = defaultdict(float)
	for row in iqc.items:
		result[row.item_code] += flt(row.accepted_qty)
	return dict(result)


def package_coverage(log):
	expected = _accepted_by_item(log)
	packaged = defaultdict(float)
	unlabelled = []
	packages = frappe.get_all(
		"RM Package",
		filters={"inbound_logistics": log.name, "status": ["!=", "Rejected"]},
		fields=["name", "item_code", "quantity", "label_applied", "current_warehouse", "last_stock_entry"],
	)
	for package in packages:
		packaged[package.item_code] += flt(package.quantity)
		if not package.label_applied:
			unlabelled.append(package.name)
	return expected, dict(packaged), packages, unlabelled


@frappe.whitelist()
def accept_at_rm_store(docname, signed_packing_list):
	require_stores_acceptance()
	doc = _load_log(docname)
	if not doc.get("purchase_receipt") or not frappe.db.exists(
		"Purchase Receipt", {"name": doc.purchase_receipt, "docstatus": 1}
	):
		frappe.throw(_("Post the GRN before RM Stores accepts the material."))
	if not signed_packing_list:
		frappe.throw(_("Attach the physically counted and signed Packing List."))
	when = now_datetime()
	return _update(
		doc,
		{
			"outward_accepted": 1,
			"outward_accepted_by": frappe.session.user,
			"outward_accepted_on": when,
			"signed_packing_list": signed_packing_list,
		},
	)


@frappe.whitelist()
def verify_putaway_and_erp(docname, stock_note_reference, stock_note_attachment=None):
	require_stores_acceptance()
	doc = _load_log(docname)
	if not doc.get("outward_accepted"):
		frappe.throw(_("RM Stores must accept the physical count and signed Packing List first."))
	if not (stock_note_reference or "").strip():
		frappe.throw(_("Enter the rack stock-note reference."))
	expected, packaged, packages, unlabelled = package_coverage(doc)
	for item, qty in expected.items():
		if abs(qty - packaged.get(item, 0)) > 0.001:
			frappe.throw(
				_("Package labels for {0} cover {1}, but IQC accepted {2}.").format(
					item, packaged.get(item, 0), qty
				)
			)
	if unlabelled:
		frappe.throw(_("Confirm labels are applied to every carton/pallet: {0}.").format(", ".join(unlabelled)))
	for package in packages:
		if package.current_warehouse != doc.rack_warehouse or not package.last_stock_entry:
			frappe.throw(
				_("Package {0} has not been barcode-put-away into allocated rack {1}.").format(
					package.name, doc.rack_warehouse
				)
			)
	when = now_datetime()
	frappe.db.set_value(
		"Purchase Receipt",
		doc.purchase_receipt,
		"lr_package_labels_verified",
		1,
		update_modified=True,
	)
	return _update(
		doc,
		{
			"stock_note_reference": stock_note_reference.strip(),
			"stock_note_attachment": stock_note_attachment,
			"erp_entry_verified": 1,
			"erp_verified_by": frappe.session.user,
			"erp_verified_on": when,
			"inward_stage": "Put Away Complete",
		},
	)


@frappe.whitelist()
def handover_documents(docname, handover_bundle_attachment):
	require_logistics_action()
	doc = _load_log(docname)
	if not doc.get("purchase_receipt") or not doc.get("iqc_reference"):
		frappe.throw(_("GRN and IQC records are required before document handover."))
	if not handover_bundle_attachment:
		frappe.throw(_("Attach the GRN, invoice, waybill/LR, IQC report, and supporting-document bundle."))
	when = now_datetime()
	return _update(
		doc,
		{
			"documents_handed_over": 1,
			"documents_handed_over_by": frappe.session.user,
			"documents_handed_over_on": when,
			"handover_bundle_attachment": handover_bundle_attachment,
			"inward_stage": "Documents Handed Over",
		},
	)


@frappe.whitelist()
def close_inward(docname):
	require_inward_manager_action()
	doc = _load_log(docname)
	checks = (
		(doc.get("erp_entry_verified"), _("rack stock note and ERP entry verification")),
		(doc.get("outward_accepted"), _("RM Stores physical acceptance")),
		(doc.get("documents_handed_over"), _("document handover to Purchase")),
	)
	missing = [label for passed, label in checks if not passed]
	if missing:
		frappe.throw(_("Complete final sign-off items: {0}.").format(", ".join(missing)))
	open_rows = [row.idx for row in doc.get("inward_exceptions") or [] if row.status != "Resolved"]
	if open_rows:
		frappe.throw(_("Resolve all quantity/damage exceptions before closure (rows {0}).").format(", ".join(map(str, open_rows))))
	when = now_datetime()
	return _update(
		doc,
		{
			"final_signoff": 1,
			"final_signed_off_by": frappe.session.user,
			"final_signed_off_on": when,
			"inward_stage": "Closed",
		},
	)


def backfill_inward_stages():
	"""Link legacy local records without inventing missing audit confirmations."""
	if not frappe.db.exists("DocType", "Inbound Logistics"):
		return
	meta = frappe.get_meta("Inbound Logistics")
	if not meta.has_field("inward_stage"):
		return
	for row in frappe.get_all(
		"Inbound Logistics",
		filters={"docstatus": 1},
		fields=["name", "purchase_order", "status", "vehicle_gate_status", "document_verification_status", "inward_stage"],
	):
		values = {}
		iqc = frappe.db.get_value(
			"IQC",
			{"inbound_logistics": row.name, "docstatus": ["<", 2]},
			["name", "status"],
			as_dict=True,
		)
		if iqc:
			values["iqc_reference"] = iqc.name
		pr = None
		if row.purchase_order:
			pr = frappe.db.sql(
				"""select pr.name
				from `tabPurchase Receipt` pr
				join `tabPurchase Receipt Item` pri on pri.parent = pr.name
				where pr.docstatus = 1 and pri.purchase_order = %s
				order by pr.posting_date desc, pr.posting_time desc limit 1""",
				(row.purchase_order,),
				as_dict=True,
			)
		if pr:
			values.update({"purchase_receipt": pr[0].name, "inward_stage": "GRN Posted"})
		elif iqc and iqc.status == "Rejected":
			values["inward_stage"] = "IQC Failed"
		elif iqc:
			values["inward_stage"] = "IQC In Progress" if iqc.status != "Passed" else "Physical Verification"
		elif row.document_verification_status == "Verified":
			values["inward_stage"] = "Documents Verified"
		elif row.vehicle_gate_status == "Approved":
			values["inward_stage"] = "Gate Approved"
		elif row.status == "Reached Warehouse":
			values["inward_stage"] = "Awaiting Gate Approval"
		if values:
			frappe.db.set_value("Inbound Logistics", row.name, values, update_modified=False)
		if iqc and iqc.status in ("Passed", "Rejected", "Moved to RM"):
			task = frappe.db.get_value("Inbound Logistics", row.name, "iqc_task")
			_complete_task(task, _("IQC {0} is {1}.").format(iqc.name, iqc.status))
	for exception in frappe.get_all(
		"Inbound Process Exception",
		filters={"status": "Resolved", "purchase_task": ["is", "set"]},
		fields=["purchase_task", "resolution_reference"],
	):
		_complete_task(
			exception.purchase_task,
			_("Inbound exception resolved with reference {0}.").format(
				exception.resolution_reference or "recorded resolution"
			),
		)
