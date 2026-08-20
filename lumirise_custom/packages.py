"""Server-side barcode controls around native Purchase Receipt and Stock Entry."""

import frappe
from frappe import _
from frappe.utils import flt


def validate_scanned_stock_entry(doc, method=None):
	"""Make a scanned LPN/source location pair authoritative on manual Stock Entry."""
	barcode = (doc.get("lr_scan_package") or "").strip()
	if not barcode:
		return
	name = frappe.db.get_value("RM Package", {"package_barcode": barcode}, "name") or barcode
	if not frappe.db.exists("RM Package", name):
		frappe.throw(_("Scanned RM package {0} does not exist.").format(barcode))
	pkg = frappe.get_doc("RM Package", name)
	if pkg.status not in ("Available", "Pending IQC"):
		frappe.throw(_("Package {0} is {1}; it cannot be used in this stock movement.").format(
			barcode, pkg.status))
	if doc.get("lr_scan_source_location") and pkg.current_warehouse != doc.lr_scan_source_location:
		frappe.throw(_("Scanned source location does not match package {0}'s current location.").format(barcode))
	if doc.purpose in ("Material Transfer", "Material Transfer for Manufacture"):
		if pkg.status != "Available":
			frappe.throw(_("Package {0} cannot move until IQC is passed and the package is released.").format(barcode))
		if doc.get("lr_scan_source_location"):
			for row in doc.items:
				if row.item_code == pkg.item_code and row.s_warehouse == pkg.current_warehouse:
					if flt(row.qty) != flt(pkg.quantity):
						frappe.throw(_("A scanned package must move in full. Create a new package for a physical split before issuing a partial quantity."))
					doc.lr_scan_verified = 1
					return
			frappe.throw(_("Stock Entry does not contain the scanned package's item and source warehouse."))


def on_purchase_receipt_submit(doc, method=None):
	"""Link packages to the standard GRN and release them only when the PO IQC is clear.

	This is intentionally conservative: it links packages by PO and item, but never
	creates packages or changes stock. Operators may use RM Package > Release after
	partial/ambiguous receipts.
	"""
	if doc.get("is_subcontracted"):
		return
	inbound = doc.get("lr_inbound_logistics")
	iqc_name = doc.get("lr_iqc")
	if not inbound or not iqc_name:
		return
	iqc_status = frappe.db.get_value("IQC", iqc_name, "status")
	if iqc_status not in ("Passed", "Moved to RM"):
		return
	warehouses = {row.item_code: row.warehouse for row in doc.items if row.item_code}
	for name in frappe.get_all(
		"RM Package",
		filters={"inbound_logistics": inbound, "iqc": iqc_name, "status": "Pending IQC"},
		pluck="name",
	):
		pkg = frappe.get_doc("RM Package", name)
		pkg.purchase_receipt = doc.name
		pkg.status = "Available"
		pkg.current_warehouse = warehouses.get(pkg.item_code) or pkg.current_warehouse
		pkg.save(ignore_permissions=True)


def on_stock_entry_submit(doc, method=None):
	"""Advance the scanned package's custody when the native movement posts."""
	barcode = (doc.get("lr_scan_package") or "").strip()
	if not barcode:
		return
	name = frappe.db.get_value("RM Package", {"package_barcode": barcode}, "name") or barcode
	if not frappe.db.exists("RM Package", name):
		return
	pkg = frappe.get_doc("RM Package", name)
	if doc.stock_entry_type == "RM Put Away":
		return  # put_away() already updates it after successful submit
	if doc.stock_entry_type == "Material Issue to Shop Floor":
		row = next((r for r in doc.items if r.item_code == pkg.item_code), None)
		if row:
			pkg.status = "Issued"
			pkg.current_warehouse = row.t_warehouse or pkg.current_warehouse
			pkg.last_stock_entry = doc.name
			pkg.save(ignore_permissions=True)


def on_purchase_receipt_cancel(doc, method=None):
	"""Return un-moved packages to Pending IQC when their GRN is cancelled."""
	for name in frappe.get_all("RM Package", filters={"purchase_receipt": doc.name}, pluck="name"):
		pkg = frappe.get_doc("RM Package", name)
		if pkg.last_stock_entry:
			continue
		pkg.status = "Pending IQC"
		pkg.purchase_receipt = None
		pkg.label_printed = 0
		pkg.label_printed_by = None
		pkg.label_printed_on = None
		pkg.label_applied = 0
		pkg.label_applied_by = None
		pkg.label_applied_on = None
		pkg.save(ignore_permissions=True)


def on_stock_entry_cancel(doc, method=None):
	"""Reverse package custody when a scanned native stock move is cancelled."""
	barcode = (doc.get("lr_scan_package") or "").strip()
	if not barcode:
		return
	name = frappe.db.get_value("RM Package", {"package_barcode": barcode}, "name") or barcode
	if not frappe.db.exists("RM Package", name):
		return
	pkg = frappe.get_doc("RM Package", name)
	if pkg.last_stock_entry != doc.name:
		return
	row = next((r for r in doc.items if r.item_code == pkg.item_code), None)
	if row:
		pkg.current_warehouse = row.s_warehouse or pkg.current_warehouse
		pkg.status = "Available"
		pkg.last_stock_entry = None
		pkg.save(ignore_permissions=True)
