"""Physical RM carton/pallet identity without replacing ERPNext stock ledgers.

RM Package is deliberately a tracking document. Purchase Receipt remains the only
inward stock posting and Stock Entry remains the only put-away/issue posting.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from lumirise_custom.action_permissions import require_doctype_permissions, require_stock_entry_permissions

PENDING_IQC = "Pending IQC"
AVAILABLE = "Available"
ISSUED = "Issued"


class RMPackage(Document):
	def before_insert(self):
		self.package_barcode = self.name
		if not self.uom and self.item_code:
			self.uom = frappe.db.get_value("Item", self.item_code, "stock_uom")

	def validate(self):
		if not self.package_barcode:
			self.package_barcode = self.name
		if flt(self.quantity) <= 0:
			frappe.throw(_("Package quantity must be greater than zero."))
		if self.batch_no:
			batch_item = frappe.db.get_value("Batch", self.batch_no, "item")
			if batch_item and batch_item != self.item_code:
				frappe.throw(_("Batch {0} belongs to item {1}, not {2}.").format(
					self.batch_no, batch_item, self.item_code))
		if self.current_warehouse and frappe.db.get_value("Warehouse", self.current_warehouse, "is_group"):
			frappe.throw(_("A package must be held in a leaf warehouse, not group warehouse {0}.").format(
				self.current_warehouse))
		if self.status in (AVAILABLE, ISSUED) and self.iqc:
			iqc_status = frappe.db.get_value("IQC", self.iqc, "status")
			if iqc_status not in ("Passed", "Moved to RM"):
				frappe.throw(_("Package cannot be available before IQC passes."))


def _package(name_or_barcode):
	name = frappe.db.get_value("RM Package", {"package_barcode": name_or_barcode}, "name") or name_or_barcode
	return frappe.get_doc("RM Package", name)


@frappe.whitelist()
def scan_package(barcode):
	"""Resolve a physical LPN and return its authoritative ERP identity."""
	if not barcode:
		frappe.throw(_("Scan an RM package barcode."))
	doc = _package(barcode.strip())
	doc.check_permission("read")
	return {
		"name": doc.name, "package_barcode": doc.package_barcode,
		"status": doc.status, "item_code": doc.item_code,
		"item_name": doc.item_name, "batch_no": doc.batch_no,
		"quantity": flt(doc.quantity), "uom": doc.uom,
		"current_warehouse": doc.current_warehouse,
		"purchase_order": doc.purchase_order, "purchase_receipt": doc.purchase_receipt,
		"inbound_logistics": doc.inbound_logistics, "iqc": doc.iqc,
	}


@frappe.whitelist()
def create_from_inbound(inbound_logistics, item_code, quantity, supplier_lot=None,
		batch_no=None, current_warehouse=None):
	"""Create one labelled package for a received inbound line.

	This creates only the native Batch master and the tracking record; it never
	creates stock. The Purchase Receipt must still be raised from passed IQC.
	"""
	frappe.has_permission("RM Package", "create", throw=True)
	log = frappe.get_doc("Inbound Logistics", inbound_logistics)
	log.check_permission("read")
	if log.docstatus != 1 or log.status != "Reached Warehouse":
		frappe.throw(_("Inbound Logistics must be submitted and Reached Warehouse before labelling."))
	if not log.get("storage_authorized"):
		frappe.throw(_("IQC must pass and storage must be authorized before package identities are generated."))
	from lumirise_custom.inward_process import _passed_iqc

	iqc = _passed_iqc(log)
	line = next((r for r in log.items if r.item_code == item_code), None)
	if not line:
		frappe.throw(_("Item {0} is not on inbound logistics {1}.").format(item_code, inbound_logistics))
	accepted_qty = sum(flt(row.accepted_qty) for row in iqc.items if row.item_code == item_code)
	packaged_qty = sum(
		flt(value)
		for value in frappe.get_all(
			"RM Package",
			filters={
				"inbound_logistics": log.name,
				"item_code": item_code,
				"status": ["!=", "Rejected"],
			},
			pluck="quantity",
		)
	)
	if flt(quantity) <= 0 or packaged_qty + flt(quantity) > accepted_qty + 0.001:
		frappe.throw(
			_("Package quantity must be positive, and total package quantity cannot exceed IQC accepted qty {0}.").format(
				accepted_qty
			)
		)
	po = log.purchase_order
	supplier = frappe.db.get_value("Purchase Order", po, "supplier") if po else None
	batch_no = batch_no or _make_batch(item_code, supplier_lot, supplier, log.name)
	warehouse = current_warehouse or log.get("receiving_warehouse") or frappe.db.get_single_value(
		"Lumirise Operations Settings", "receiving_warehouse")
	if not warehouse:
		frappe.throw(_("Configure Receiving / Staging in Lumirise Operations Settings."))
	pr_name = log.get("purchase_receipt")
	grn_posted = bool(pr_name and frappe.db.exists("Purchase Receipt", {"name": pr_name, "docstatus": 1}))
	doc = frappe.get_doc({
		"doctype": "RM Package", "item_code": item_code, "batch_no": batch_no,
		"supplier": supplier, "supplier_lot": supplier_lot,
		"quantity": flt(quantity), "current_warehouse": warehouse,
		"purchase_order": po, "inbound_logistics": log.name,
		"purchase_receipt": pr_name if grn_posted else None,
		"iqc": iqc.name,
		"status": AVAILABLE if grn_posted else PENDING_IQC,
	})
	doc.insert()
	return doc


def _make_batch(item_code, supplier_lot, supplier, inbound_name):
	lot = (supplier_lot or "").strip() or f"INW-{inbound_name}"
	base = f"{item_code}-{lot}"[:140]
	name = base
	idx = 1
	while frappe.db.exists("Batch", name):
		if frappe.db.get_value("Batch", name, "item") == item_code:
			return name
		idx += 1
		name = f"{base[:130]}-{idx}"
	require_doctype_permissions("Batch", "create")
	batch = frappe.get_doc({
		"doctype": "Batch", "batch_id": name, "item": item_code,
		"supplier": supplier, "description": f"Lumirise inward batch from {inbound_name}",
		"reference_doctype": "Inbound Logistics", "reference_name": inbound_name,
		"lr_supplier_lot": supplier_lot, "lr_inbound_logistics": inbound_name,
		"lr_iqc_status": "Pending IQC",
	})
	batch.insert(ignore_permissions=True)
	return batch.name


@frappe.whitelist()
def release_after_grn(package, purchase_receipt, iqc=None):
	"""Release a labelled package only after the standard GRN and IQC are clear."""
	pkg = _package(package)
	pkg.check_permission("write")
	pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
	pr.check_permission("read")
	if pr.docstatus != 1:
		frappe.throw(_("Purchase Receipt must be submitted before releasing a package."))
	if iqc:
		frappe.has_permission("IQC", "read", iqc, throw=True)
		iqc_status = frappe.db.get_value("IQC", iqc, "status")
		if iqc_status not in ("Passed", "Moved to RM"):
			frappe.throw(_("IQC has not passed."))
	pkg.purchase_receipt = pr.name
	pkg.iqc = iqc or pkg.iqc
	pkg.current_warehouse = next((r.warehouse for r in pr.items if r.item_code == pkg.item_code), pkg.current_warehouse)
	pkg.status = AVAILABLE
	pkg.save()
	if pkg.batch_no and frappe.db.exists("Batch", pkg.batch_no):
		frappe.db.set_value("Batch", pkg.batch_no, "lr_iqc_status", "Passed")
	return pkg


@frappe.whitelist()
def put_away(package, destination_warehouse):
	"""Post a native Material Transfer for one complete physical package."""
	pkg = _package(package)
	pkg.check_permission("write")
	destination_warehouse = _resolve_location(destination_warehouse)
	frappe.has_permission("Warehouse", "read", destination_warehouse, throw=True)
	require_stock_entry_permissions(submit=True)
	if pkg.status != AVAILABLE:
		frappe.throw(_("Only an IQC-cleared Available package can be put away."))
	if not pkg.get("label_applied"):
		frappe.throw(_("Print and confirm the physical package label before put-away."))
	if not destination_warehouse or destination_warehouse == pkg.current_warehouse:
		frappe.throw(_("Choose a different destination leaf warehouse."))
	if frappe.db.get_value("Warehouse", destination_warehouse, "is_group"):
		frappe.throw(_("Destination must be a leaf location warehouse."))
	company = frappe.db.get_value("Warehouse", pkg.current_warehouse, "company")
	se = frappe.get_doc({
		"doctype": "Stock Entry", "stock_entry_type": "RM Put Away",
		"company": company, "from_warehouse": pkg.current_warehouse,
		"to_warehouse": destination_warehouse,
		"custom_narration": f"Barcode put-away {pkg.package_barcode}",
		"lr_scan_package": pkg.package_barcode,
		"lr_scan_source_location": pkg.current_warehouse,
		"items": [{"item_code": pkg.item_code, "qty": pkg.quantity,
			"s_warehouse": pkg.current_warehouse, "t_warehouse": destination_warehouse,
			"batch_no": pkg.batch_no, "uom": pkg.uom or "Nos",
			"stock_uom": pkg.uom or "Nos", "conversion_factor": 1}],
	})
	se.insert(ignore_permissions=True)
	se.submit()
	pkg.current_warehouse = destination_warehouse
	pkg.last_stock_entry = se.name
	pkg.save(ignore_permissions=True)
	return {"package": pkg.name, "stock_entry": se.name, "destination": destination_warehouse}


def _resolve_location(value):
	"""Resolve either a warehouse name or the barcode printed on its rack/bin."""
	value = (value or "").strip()
	if not value:
		frappe.throw(_("Scan or enter the destination location barcode."))
	name = frappe.db.get_value("Warehouse", {"lr_location_barcode": value}, "name")
	name = name or (value if frappe.db.exists("Warehouse", value) else None)
	if not name:
		frappe.throw(_("Location barcode {0} does not match a Warehouse.").format(value))
	status = frappe.db.get_value("Warehouse", name, "lr_location_status")
	if status and status != "Available":
		frappe.throw(_("Location {0} is {1} and cannot receive a package.").format(name, status))
	return name


@frappe.whitelist()
def confirm_label_applied(package):
	"""Post-GRN physical confirmation that the printed LPN is on the carton/pallet."""
	require_stock_entry_permissions(submit=False)
	pkg = _package(package)
	pkg.check_permission("write")
	if pkg.status != AVAILABLE or not pkg.purchase_receipt:
		frappe.throw(_("Post the GRN and release the package before confirming its label."))
	when = now_datetime()
	frappe.db.set_value(
		"RM Package",
		pkg.name,
		{
			"label_printed": 1,
			"label_printed_by": frappe.session.user,
			"label_printed_on": when,
			"label_applied": 1,
			"label_applied_by": frappe.session.user,
			"label_applied_on": when,
		},
		update_modified=True,
	)
	return {"package": pkg.name, "label_applied": 1}
