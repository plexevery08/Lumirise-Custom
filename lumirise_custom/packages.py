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
	pos = {r.purchase_order for r in doc.items if r.get("purchase_order")}
	for po in pos:
		iqcs = frappe.get_all("IQC", filters={"purchase_order": po, "docstatus": 1,
			"status": ["in", ["Passed", "Moved to RM"]]}, fields=["name", "status"], limit=1)
		if not iqcs:
			continue
		for row in doc.items:
			packages = frappe.get_all("RM Package", filters={
				"purchase_order": po, "item_code": row.item_code,
				"status": "Pending IQC",
			}, pluck="name")
			for name in packages:
				pkg = frappe.get_doc("RM Package", name)
				pkg.purchase_receipt = doc.name
				pkg.iqc = iqcs[0].name
				pkg.status = "Available"
				pkg.current_warehouse = row.warehouse or pkg.current_warehouse
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
