"""End-to-end RM package barcode service.

ERPNext's Batch, Bin, Stock Ledger Entry and Stock Entry remain the inventory truth.
This module adds the physical package identity (LPN) and an immutable scan trail.
"""

import json
import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from lumirise_custom import defaults as config

PACKAGE_DT = "RM Receiving Package"
PUTAWAY_TYPE = "RM Package Put Away"
ISSUE_TYPE = "Material Issue to Shop Floor"


def _enabled():
	return config.flag("enable_rm_barcode_system", default=True)


def _require_enabled():
	if not _enabled():
		frappe.throw(_("Enable the RM Barcode System in Lumirise Operations Settings."))


def _as_list(value):
	if isinstance(value, str):
		return json.loads(value)
	return value or []


def _clean_code(value, length=36):
	return re.sub(r"[^A-Za-z0-9-]+", "-", value or "").strip("-")[:length]


def _is_descendant(warehouse, parent):
	if not warehouse or not parent:
		return False
	if warehouse == parent:
		return True
	bounds = frappe.db.get_value("Warehouse", parent, ["lft", "rgt"], as_dict=True)
	child = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=True)
	return bool(bounds and child and child.lft > bounds.lft and child.rgt < bounds.rgt)


def _get_or_create_batch(item_code, inbound, supplier_lot=None, manufacturing_date=None, expiry_date=None):
	if not frappe.db.get_value("Item", item_code, "has_batch_no"):
		if config.flag("require_batch_for_rm_packages", default=True):
			frappe.throw(
				_("Item {0} must have Has Batch No enabled before package labels are generated.").format(item_code)
			)
		return None

	batch_id = "RMB-{0}-{1}".format(_clean_code(inbound, 15), _clean_code(item_code, 15))
	if supplier_lot:
		batch_id += "-" + _clean_code(supplier_lot, 15)
	existing = frappe.db.get_value("Batch", {"item": item_code, "batch_id": batch_id}, "name")
	if existing:
		return existing

	doc = frappe.get_doc({"doctype": "Batch", "item": item_code, "batch_id": batch_id})
	if manufacturing_date and doc.meta.has_field("manufacturing_date"):
		doc.manufacturing_date = manufacturing_date
	if expiry_date and doc.meta.has_field("expiry_date"):
		doc.expiry_date = expiry_date
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def create_receiving_packages(inbound_logistics, packages):
	"""Generate Lumirise labels at unloading.

	``packages`` is a list of {item_code, package_count, total_qty, supplier_lot,
	package_type, manufacturing_date, expiry_date}. Equal quantities are generated;
	the final package absorbs any decimal remainder.
	"""
	_require_enabled()
	frappe.has_permission("Inbound Logistics", "write", inbound_logistics, throw=True)
	log = frappe.get_doc("Inbound Logistics", inbound_logistics)
	if log.docstatus != 1 or log.status != "Reached Warehouse":
		frappe.throw(_("Submit the Inbound Logistics and mark it Reached Warehouse first."))
	submitted_iqc = frappe.db.get_value("IQC", {"inbound_logistics": log.name, "docstatus": 1}, "name")
	if submitted_iqc:
		frappe.throw(_("IQC {0} is already submitted; package labels can no longer be added.").format(submitted_iqc))
	draft_iqc = frappe.db.get_value("IQC", {"inbound_logistics": log.name, "docstatus": 0}, "name")

	available = defaultdict(float)
	for row in log.items:
		available[row.item_code] += flt(row.qty)
	already = defaultdict(float)
	for row in frappe.get_all(PACKAGE_DT, {"inbound_logistics": log.name}, ["item_code", "received_qty"]):
		already[row.item_code] += flt(row.received_qty)

	created = []
	for spec in _as_list(packages):
		item = spec.get("item_code")
		count = cint(spec.get("package_count"))
		total = flt(spec.get("total_qty"))
		if item not in available:
			frappe.throw(_("Item {0} is not in Inbound Logistics {1}.").format(item, log.name))
		if count <= 0 or total <= 0:
			frappe.throw(_("Package count and total quantity must be greater than zero for {0}.").format(item))
		if already[item] + total > available[item] + 0.001:
			frappe.throw(_("Package quantity for {0} exceeds the inbound quantity still available for labelling.").format(item))

		batch = _get_or_create_batch(
			item, log.name, spec.get("supplier_lot"), spec.get("manufacturing_date"), spec.get("expiry_date")
		)
		base = flt(total / count, 6)
		assigned = 0.0
		for index in range(1, count + 1):
			qty = flt(total - assigned, 6) if index == count else base
			pkg = frappe.get_doc(
				{
					"doctype": PACKAGE_DT,
					"inbound_logistics": log.name,
					"purchase_order": log.purchase_order,
					"iqc": draft_iqc,
					"item_code": item,
					"batch_no": batch,
					"supplier_lot": spec.get("supplier_lot"),
					"manufacturing_date": spec.get("manufacturing_date"),
					"expiry_date": spec.get("expiry_date"),
					"package_type": spec.get("package_type") or "Carton",
					"package_index": index,
					"total_packages": count,
					"received_qty": qty,
					"remaining_qty": 0,
					"status": "Pending IQC",
				}
			).insert(ignore_permissions=True)
			_append_movement(pkg, "Received", qty, None, None, "Inbound Logistics", log.name)
			_system_save(pkg)
			created.append(pkg.name)
			assigned += qty
		already[item] += total

	return {"created": created, "print_format": "Lumirise RM Package Label"}


@frappe.whitelist()
def create_opening_packages(item_code, warehouse, batch_no, package_count, total_qty, stock_reconciliation=None):
	"""Represent already-posted stock with LPNs without touching the stock ledger.

	System Manager only. The physical count and any quantity correction must be
	posted through Stock Reconciliation first; this endpoint only creates labels.
	"""
	_require_enabled()
	frappe.only_for("System Manager")
	count, total = cint(package_count), flt(total_qty)
	if count <= 0 or total <= 0:
		frappe.throw(_("Package count and total quantity must be greater than zero."))
	_validate_location(warehouse, item_code, 0)
	if batch_no and frappe.db.get_value("Batch", batch_no, "item") != item_code:
		frappe.throw(_("Batch {0} does not belong to item {1}.").format(batch_no, item_code))
	if config.flag("require_batch_for_rm_packages", default=True) and not batch_no:
		frappe.throw(_("Select the existing ERPNext Batch for opening stock."))
	if batch_no and not cint(frappe.db.get_value("Item", item_code, "has_batch_no")):
		frappe.throw(_("Item {0} is not batch-enabled.").format(item_code))
	bin_qty = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
	represented = flt(frappe.db.sql(
		"""SELECT COALESCE(SUM(remaining_qty),0) FROM `tabRM Receiving Package`
		WHERE item_code=%s AND current_warehouse=%s AND status='Stored'""",
		(item_code, warehouse),
	)[0][0])
	if represented + total > bin_qty + 0.001:
		frappe.throw(_("Opening labels would represent {0}, but ERP stock in {1} is only {2}.").format(
			represented + total, warehouse, bin_qty
		))

	created = []
	base, assigned = flt(total / count, 6), 0.0
	for index in range(1, count + 1):
		qty = flt(total - assigned, 6) if index == count else base
		pkg = frappe.get_doc(
			{
				"doctype": PACKAGE_DT,
				"is_opening_stock": 1,
				"stock_reconciliation": stock_reconciliation,
				"item_code": item_code,
				"batch_no": batch_no,
				"package_index": index,
				"total_packages": count,
				"package_type": "Carton",
				"received_qty": qty,
				"accepted_qty": qty,
				"remaining_qty": qty,
				"status": "Stored",
				"current_warehouse": warehouse,
			}
		).insert(ignore_permissions=True)
		_append_movement(pkg, "Received", qty, None, warehouse,
			"Stock Reconciliation" if stock_reconciliation else None, stock_reconciliation)
		_system_save(pkg)
		created.append(pkg.name)
		assigned += qty
	return {"created": created, "print_format": "Lumirise RM Package Label"}


def link_packages_to_iqc(doc, method=None):
	if not doc.inbound_logistics:
		return
	for row in frappe.get_all(
		PACKAGE_DT, filters={"inbound_logistics": doc.inbound_logistics}, fields=["name", "iqc"]
	):
		if not row.iqc:
			frappe.db.set_value(PACKAGE_DT, row.name, "iqc", doc.name, update_modified=False)


@frappe.whitelist()
def record_package_qc(iqc, package_barcode, accepted_qty, rejected_qty=0):
	_require_enabled()
	frappe.has_permission("IQC", "write", iqc, throw=True)
	doc = frappe.get_doc("IQC", iqc)
	if doc.docstatus != 0:
		frappe.throw(_("Package results can only be scanned while the IQC is in Draft."))
	pkg = _package_by_barcode(package_barcode)
	if pkg.inbound_logistics != doc.inbound_logistics:
		frappe.throw(_("Package {0} does not belong to this inbound consignment.").format(pkg.name))
	accepted, rejected = flt(accepted_qty), flt(rejected_qty)
	if accepted < 0 or rejected < 0 or abs((accepted + rejected) - flt(pkg.received_qty)) > 0.001:
		frappe.throw(_("Accepted plus rejected quantity must equal package quantity {0}.").format(pkg.received_qty))
	pkg.iqc = doc.name
	rejected_package = None
	if accepted and rejected:
		# A physical package cannot simultaneously go to the accepted and rejection
		# stores. Split it into two Lumirise identities and print the new reject label.
		original_received = pkg.received_qty
		pkg.received_qty = accepted
		pkg.accepted_qty = accepted
		pkg.rejected_qty = 0
		pkg.status = "IQC Passed"
		rejected_package = frappe.get_doc(
			{
				"doctype": PACKAGE_DT,
				"inbound_logistics": pkg.inbound_logistics,
				"iqc": doc.name,
				"purchase_order": pkg.purchase_order,
				"item_code": pkg.item_code,
				"batch_no": pkg.batch_no,
				"supplier_lot": pkg.supplier_lot,
				"manufacturing_date": pkg.manufacturing_date,
				"expiry_date": pkg.expiry_date,
				"package_type": pkg.package_type,
				"package_index": pkg.package_index,
				"total_packages": pkg.total_packages,
				"received_qty": rejected,
				"accepted_qty": 0,
				"rejected_qty": rejected,
				"remaining_qty": 0,
				"status": "Rejected",
				"remarks": _("Split from {0} during IQC; original package quantity was {1}.").format(
					pkg.name, original_received
				),
			}
		).insert(ignore_permissions=True)
	else:
		pkg.accepted_qty = accepted
		pkg.rejected_qty = rejected
		pkg.status = "IQC Passed" if accepted else "Rejected"
	pkg.last_scan_on = now_datetime()
	pkg.last_scan_by = frappe.session.user
	_system_save(pkg)
	_sync_iqc_totals(doc)
	result = _package_payload(pkg)
	result["rejected_package"] = rejected_package.name if rejected_package else None
	return result


def _sync_iqc_totals(iqc):
	totals = defaultdict(lambda: [0.0, 0.0])
	for pkg in frappe.get_all(PACKAGE_DT, {"iqc": iqc.name}, ["item_code", "accepted_qty", "rejected_qty"]):
		totals[pkg.item_code][0] += flt(pkg.accepted_qty)
		totals[pkg.item_code][1] += flt(pkg.rejected_qty)
	for row in iqc.items:
		if row.item_code in totals:
			row.accepted_qty, row.rejected_qty = totals[row.item_code]
	iqc.save(ignore_permissions=True)


def validate_iqc_packages(doc, method=None):
	packages = frappe.get_all(PACKAGE_DT, {"inbound_logistics": doc.inbound_logistics},
		["name", "item_code", "received_qty", "accepted_qty", "rejected_qty"])
	if not packages:
		return
	package_totals = defaultdict(lambda: [0.0, 0.0, 0.0])
	for pkg in packages:
		if abs(flt(pkg.received_qty) - flt(pkg.accepted_qty) - flt(pkg.rejected_qty)) > 0.001:
			frappe.throw(_("Scan a complete IQC result for package {0} before submitting.").format(pkg.name))
		package_totals[pkg.item_code][0] += flt(pkg.received_qty)
		package_totals[pkg.item_code][1] += flt(pkg.accepted_qty)
		package_totals[pkg.item_code][2] += flt(pkg.rejected_qty)
	for row in doc.items:
		received, accepted, rejected = package_totals[row.item_code]
		if abs(received - flt(row.received_qty)) > 0.001:
			frappe.throw(_("Package labels for {0} total {1}, but IQC received quantity is {2}.").format(
				row.item_code, received, row.received_qty
			))
		if abs(accepted - flt(row.accepted_qty)) > 0.001 or abs(rejected - flt(row.rejected_qty)) > 0.001:
			frappe.throw(_("IQC totals for {0} must come from the scanned package results.").format(row.item_code))


def on_iqc_submit(doc, method=None):
	for name in frappe.get_all(PACKAGE_DT, {"iqc": doc.name}, pluck="name"):
		pkg = frappe.get_doc(PACKAGE_DT, name)
		pkg.status = "IQC Passed" if flt(pkg.accepted_qty) else "Rejected"
		if flt(pkg.accepted_qty):
			_append_movement(pkg, "IQC Accepted", pkg.accepted_qty, None, None, "IQC", doc.name)
		if flt(pkg.rejected_qty):
			_append_movement(pkg, "IQC Rejected", pkg.rejected_qty, None, None, "IQC", doc.name)
		_system_save(pkg)


def on_iqc_cancel(doc, method=None):
	for name in frappe.get_all(PACKAGE_DT, {"iqc": doc.name}, pluck="name"):
		pkg = frappe.get_doc(PACKAGE_DT, name)
		pkg.status = "Pending IQC"
		pkg.accepted_qty = pkg.rejected_qty = 0
		_reverse_movements(pkg, "IQC", doc.name)
		_system_save(pkg)


def prepare_grn_rows(iqc, pr):
	"""Replace accepted PR quantities with one row per item/batch package group."""
	packages = frappe.get_all(
		PACKAGE_DT, {"iqc": iqc.name},
		["name", "item_code", "batch_no", "accepted_qty", "rejected_qty"]
	)
	if not packages:
		return pr
	groups = defaultdict(lambda: {"accepted": 0.0, "rejected": 0.0, "packages": []})
	for pkg in packages:
		key = (pkg.item_code, pkg.batch_no or "")
		groups[key]["accepted"] += flt(pkg.accepted_qty)
		groups[key]["rejected"] += flt(pkg.rejected_qty)
		groups[key]["packages"].append(pkg.name)

	source = {}
	source_counts = defaultdict(int)
	for row in pr.items:
		source.setdefault(row.item_code, row.as_dict())
		source_counts[row.item_code] += 1
	new_rows = []
	for (item, batch), values in groups.items():
		if item not in source:
			frappe.throw(_("No Purchase Order row was mapped for package item {0}.").format(item))
		if source_counts[item] > 1:
			frappe.throw(_("Purchase Order has duplicate rows for {0}. Consolidate them before package GRN mapping.").format(item))
		data = {
			key: value for key, value in source[item].items()
			if key not in {"name", "parent", "parenttype", "parentfield", "idx", "docstatus"}
		}
		data.update(
			{
				"qty": values["accepted"],
				"received_qty": values["accepted"] + values["rejected"],
				"rejected_qty": values["rejected"],
				"batch_no": batch or None,
				"use_serial_batch_fields": 1 if batch else 0,
				"lr_rm_package_refs": "\n".join(values["packages"]),
			}
		)
		new_rows.append(data)
	pr.set("items", [])
	for data in new_rows:
		pr.append("items", data)
	return pr


def on_grn_submit(doc, method=None):
	if not doc.get("lr_iqc"):
		return
	staging = config.receiving_warehouse() or config.rm_warehouse()
	for row in doc.items:
		for name in (row.get("lr_rm_package_refs") or "").splitlines():
			if not name:
				continue
			pkg = frappe.get_doc(PACKAGE_DT, name)
			pkg.purchase_receipt = doc.name
			pkg.purchase_receipt_item = row.name
			pkg.current_warehouse = staging if flt(pkg.accepted_qty) else row.rejected_warehouse
			pkg.remaining_qty = pkg.accepted_qty or pkg.rejected_qty
			pkg.status = "Ready to Put Away" if flt(pkg.accepted_qty) else "Rejected"
			_append_movement(pkg, "GRN", pkg.accepted_qty or pkg.rejected_qty, None,
				pkg.current_warehouse, "Purchase Receipt", doc.name, row.name)
			_system_save(pkg)


def on_grn_cancel(doc, method=None):
	for name in frappe.get_all(PACKAGE_DT, {"purchase_receipt": doc.name}, pluck="name"):
		pkg = frappe.get_doc(PACKAGE_DT, name)
		pkg.purchase_receipt = None
		pkg.purchase_receipt_item = None
		pkg.current_warehouse = None
		pkg.remaining_qty = 0
		pkg.status = "IQC Passed" if flt(pkg.accepted_qty) else "Rejected"
		_reverse_movements(pkg, "Purchase Receipt", doc.name)
		_system_save(pkg)


@frappe.whitelist()
def putaway_package(package_barcode, location_barcode):
	_require_enabled()
	frappe.has_permission("Stock Entry", "create", throw=True)
	pkg = _package_by_barcode(package_barcode, lock=True)
	location = _warehouse_by_barcode(location_barcode)
	if pkg.status != "Ready to Put Away":
		frappe.throw(_("Package {0} is not ready for put-away (current status: {1}).").format(pkg.name, pkg.status))
	_validate_location(location, pkg.item_code, pkg.remaining_qty)
	staging = config.receiving_warehouse()
	if not staging:
		frappe.throw(_("Configure a Receiving / Staging warehouse before using barcode put-away."))
	if pkg.current_warehouse != staging:
		frappe.throw(_("Package {0} is not currently in the Receiving / Staging warehouse.").format(pkg.name))

	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": PUTAWAY_TYPE,
			"purpose": "Material Transfer",
			"company": config.get_company(),
			"lr_scan_location_barcode": location_barcode,
			"lr_scan_package_barcode": pkg.barcode_value,
			"items": [
				{
					"item_code": pkg.item_code,
					"qty": pkg.remaining_qty,
					"s_warehouse": staging,
					"t_warehouse": location,
					"batch_no": pkg.batch_no,
					"use_serial_batch_fields": 1 if pkg.batch_no else 0,
					"lr_rm_package": pkg.name,
				}
			],
		}
	)
	se.insert()
	se.submit()
	return {"stock_entry": se.name, "package": pkg.name, "location": location}


@frappe.whitelist()
def get_package_scan_context(package_barcode, location_barcode=None):
	_require_enabled()
	pkg = _package_by_barcode(package_barcode)
	location = _warehouse_by_barcode(location_barcode) if location_barcode else None
	if location:
		_validate_location(location, pkg.item_code, 0)
	data = _package_payload(pkg)
	data["location"] = location
	return data


@frappe.whitelist()
def split_package_for_issue(package_barcode, qty):
	"""Create a child LPN for a partial pick so one barcode never occupies two places."""
	_require_enabled()
	frappe.has_permission("Stock Entry", "create", throw=True)
	pkg = _package_by_barcode(package_barcode, lock=True)
	qty = flt(qty)
	if pkg.status not in ("Stored", "Issued to Shop Floor", "In Production", "Partially Consumed"):
		frappe.throw(_("Only stored or in-production material can be split for movement."))
	if qty <= 0 or qty >= flt(pkg.remaining_qty) - 0.001:
		frappe.throw(_("Split quantity must be greater than zero and less than the package balance."))
	child = frappe.get_doc(
		{
			"doctype": PACKAGE_DT,
			"is_opening_stock": pkg.is_opening_stock,
			"inbound_logistics": pkg.inbound_logistics,
			"iqc": pkg.iqc,
			"purchase_order": pkg.purchase_order,
			"purchase_receipt": pkg.purchase_receipt,
			"purchase_receipt_item": pkg.purchase_receipt_item,
			"stock_reconciliation": pkg.stock_reconciliation,
			"item_code": pkg.item_code,
			"batch_no": pkg.batch_no,
			"supplier_lot": pkg.supplier_lot,
			"manufacturing_date": pkg.manufacturing_date,
			"expiry_date": pkg.expiry_date,
			"package_type": pkg.package_type,
			"package_index": pkg.package_index,
			"total_packages": pkg.total_packages,
			"received_qty": qty,
			"accepted_qty": qty,
			"remaining_qty": qty,
			"status": pkg.status,
			"current_warehouse": pkg.current_warehouse,
			"remarks": _("Split from {0} for a partial production issue.").format(pkg.name),
		}
	).insert(ignore_permissions=True)
	pkg.received_qty = flt(pkg.received_qty) - qty
	pkg.accepted_qty = flt(pkg.accepted_qty) - qty
	pkg.remaining_qty = flt(pkg.remaining_qty) - qty
	_append_movement(pkg, "Split", qty, pkg.current_warehouse, pkg.current_warehouse,
		PACKAGE_DT, child.name)
	_append_movement(child, "Split", qty, pkg.current_warehouse, pkg.current_warehouse,
		PACKAGE_DT, pkg.name)
	_system_save(pkg)
	_system_save(child)
	return {"package": _package_payload(child), "remainder": _package_payload(pkg)}


def split_pre_grn_sample_package(package_barcode, qty, iqc):
	"""Reserve a whole child LPN for a physical IQC sample before stock is owned."""
	pkg = _package_by_barcode(package_barcode, lock=True)
	qty = flt(qty)
	if pkg.inbound_logistics != iqc.inbound_logistics:
		frappe.throw(_("Package {0} does not belong to IQC {1}.").format(pkg.name, iqc.name))
	if pkg.status != "Pending IQC" or flt(pkg.accepted_qty) or flt(pkg.rejected_qty):
		frappe.throw(_("Take the sample before recording this package's IQC result."))
	if qty <= 0 or qty > flt(pkg.received_qty) + 0.001:
		frappe.throw(_("Sample quantity exceeds package {0}.").format(pkg.name))
	if abs(qty - flt(pkg.received_qty)) <= 0.001:
		return pkg, False

	child = frappe.get_doc(
		{
			"doctype": PACKAGE_DT,
			"inbound_logistics": pkg.inbound_logistics,
			"iqc": iqc.name,
			"purchase_order": pkg.purchase_order,
			"item_code": pkg.item_code,
			"batch_no": pkg.batch_no,
			"supplier_lot": pkg.supplier_lot,
			"manufacturing_date": pkg.manufacturing_date,
			"expiry_date": pkg.expiry_date,
			"package_type": "Other",
			"received_qty": qty,
			"remaining_qty": 0,
			"status": "Pending IQC",
			"remarks": _("IQC sample split from {0}.").format(pkg.name),
		}
	).insert(ignore_permissions=True)
	pkg.received_qty = flt(pkg.received_qty) - qty
	_append_movement(pkg, "Split", qty, None, None, PACKAGE_DT, child.name)
	_append_movement(child, "Split", qty, None, None, PACKAGE_DT, pkg.name)
	_system_save(pkg)
	_system_save(child)
	return child, True


def validate_stock_entry_packages(doc, method=None):
	if not _enabled():
		return
	enforce = config.flag("enforce_rm_package_scan", default=False)
	rm_root = config.rm_warehouse() if enforce else None
	seen = defaultdict(float)
	for row in doc.items:
		tracked = cint(frappe.db.get_value("Item", row.item_code, "lr_rm_barcode_tracking"))
		from_rm = _is_descendant(row.s_warehouse, rm_root) if enforce else False
		package_stock = bool(
			enforce and row.s_warehouse and frappe.db.exists(
				PACKAGE_DT,
				{"item_code": row.item_code, "current_warehouse": row.s_warehouse, "remaining_qty": [">", 0]},
			)
		)
		if enforce and tracked and (from_rm or package_stock) and not row.get("lr_rm_package"):
			frappe.throw(_("Row {0} ({1}): scan the RM package barcode before submission.").format(row.idx, row.item_code))
		if not row.get("lr_rm_package"):
			continue
		pkg = frappe.get_doc(PACKAGE_DT, row.lr_rm_package)
		if pkg.item_code != row.item_code:
			frappe.throw(_("Row {0}: package {1} contains {2}, not {3}.").format(row.idx, pkg.name, pkg.item_code, row.item_code))
		if pkg.current_warehouse != row.s_warehouse:
			frappe.throw(_("Row {0}: package {1} is in {2}, not {3}.").format(row.idx, pkg.name, pkg.current_warehouse, row.s_warehouse))
		if pkg.batch_no and row.get("batch_no") != pkg.batch_no:
			frappe.throw(_("Row {0}: batch must be {1} for package {2}.").format(row.idx, pkg.batch_no, pkg.name))
		seen[pkg.name] += flt(row.qty)
		if seen[pkg.name] > flt(pkg.remaining_qty) + 0.001:
			frappe.throw(_("Package {0} has only {1} remaining.").format(pkg.name, pkg.remaining_qty))
	for package_name, qty in seen.items():
		remaining = flt(frappe.db.get_value(PACKAGE_DT, package_name, "remaining_qty"))
		if abs(qty - remaining) > 0.001:
			frappe.throw(_("Move the complete package {0}. The scanner will create a child label for a partial pick.").format(
				package_name
			))


def validate_warehouse_location_barcode(doc, method=None):
	barcode = (doc.get("lr_location_barcode") or "").strip()
	if not barcode:
		return
	duplicate = frappe.db.get_value(
		"Warehouse", {"lr_location_barcode": barcode, "name": ["!=", doc.name]}, "name"
	)
	if duplicate:
		frappe.throw(_("Location barcode {0} is already assigned to {1}.").format(barcode, duplicate))


def on_stock_entry_submit(doc, method=None):
	for row in doc.items:
		if not row.get("lr_rm_package"):
			continue
		pkg = _locked_package(row.lr_rm_package)
		if doc.stock_entry_type == PUTAWAY_TYPE:
			pkg.current_warehouse = row.t_warehouse
			pkg.status = "Stored"
			movement = "Put Away"
		elif doc.stock_entry_type == ISSUE_TYPE:
			pkg.current_warehouse = row.t_warehouse
			pkg.status = "Issued to Shop Floor"
			movement = "Issue"
		elif doc.purpose in ("Manufacture", "Material Consumption for Manufacture", "Material Issue"):
			pkg.remaining_qty = flt(pkg.remaining_qty) - flt(row.qty)
			pkg.status = "Consumed" if flt(pkg.remaining_qty) <= 0.001 else "Partially Consumed"
			if pkg.status == "Consumed":
				pkg.current_warehouse = None
			movement = "Issue"
		else:
			pkg.current_warehouse = row.t_warehouse or pkg.current_warehouse
			if pkg.current_warehouse == config.iqc_lab_warehouse():
				pkg.status = "In IQC Lab"
			elif pkg.current_warehouse == config.receiving_warehouse():
				pkg.status = "Ready to Put Away"
			else:
				pkg.status = "Stored" if _is_descendant(pkg.current_warehouse, config.rm_warehouse()) else "In Production"
			movement = "Transfer"
		pkg.last_scan_on = now_datetime()
		pkg.last_scan_by = frappe.session.user
		_append_movement(pkg, movement, row.qty, row.s_warehouse, row.t_warehouse,
			"Stock Entry", doc.name, row.name)
		_system_save(pkg)


def on_stock_entry_cancel(doc, method=None):
	for row in doc.items:
		if not row.get("lr_rm_package"):
			continue
		pkg = _locked_package(row.lr_rm_package)
		if doc.purpose in ("Manufacture", "Material Consumption for Manufacture", "Material Issue"):
			pkg.remaining_qty = flt(pkg.remaining_qty) + flt(row.qty)
		pkg.current_warehouse = row.s_warehouse
		if doc.stock_entry_type == PUTAWAY_TYPE:
			pkg.status = "Ready to Put Away"
		elif row.s_warehouse == config.iqc_lab_warehouse():
			pkg.status = "In IQC Lab"
		elif row.s_warehouse == config.receiving_warehouse():
			pkg.status = "Ready to Put Away"
		elif _is_descendant(row.s_warehouse, config.rm_warehouse()):
			pkg.status = "Stored"
		else:
			pkg.status = "In Production"
		_reverse_movements(pkg, "Stock Entry", doc.name, row.name)
		_system_save(pkg)


def _locked_package(name):
	frappe.db.sql("SELECT name FROM `tabRM Receiving Package` WHERE name=%s FOR UPDATE", name)
	return frappe.get_doc(PACKAGE_DT, name)


def _system_save(pkg):
	pkg.flags.rm_barcode_system_update = True
	pkg.save(ignore_permissions=True)


def _package_by_barcode(barcode, lock=False):
	name = frappe.db.get_value(PACKAGE_DT, {"barcode_value": barcode}, "name") or (
		barcode if frappe.db.exists(PACKAGE_DT, barcode) else None
	)
	if not name:
		frappe.throw(_("Unknown RM package barcode: {0}").format(barcode))
	return _locked_package(name) if lock else frappe.get_doc(PACKAGE_DT, name)


def _warehouse_by_barcode(barcode):
	name = frappe.db.get_value("Warehouse", {"lr_location_barcode": barcode}, "name") or (
		barcode if frappe.db.exists("Warehouse", barcode) else None
	)
	if not name:
		frappe.throw(_("Unknown warehouse/location barcode: {0}").format(barcode))
	return name


def _validate_location(warehouse, item_code, incoming_qty):
	if not _is_descendant(warehouse, config.rm_warehouse()):
		frappe.throw(_("Location {0} is not inside the configured Raw Material Store hierarchy.").format(warehouse))
	row = frappe.db.get_value(
		"Warehouse", warehouse,
		["is_group", "disabled", "lr_slot_status", "lr_slot_capacity", "lr_slot_capacity_uom", "lr_allowed_item_group"],
		as_dict=True,
	)
	if not row or row.is_group or row.disabled:
		frappe.throw(_("Choose an enabled leaf warehouse/rack location."))
	if row.lr_slot_status and row.lr_slot_status != "Available":
		frappe.throw(_("Location {0} is {1}.").format(warehouse, row.lr_slot_status))
	if row.lr_allowed_item_group:
		group = frappe.db.get_value("Item", item_code, "item_group")
		if group != row.lr_allowed_item_group:
			frappe.throw(_("Location {0} only allows item group {1}.").format(warehouse, row.lr_allowed_item_group))
	if row.lr_slot_capacity_uom:
		stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
		if stock_uom != row.lr_slot_capacity_uom:
			frappe.throw(_("Location {0} capacity is measured in {1}; item {2} uses {3}.").format(
				warehouse, row.lr_slot_capacity_uom, item_code, stock_uom
			))
	if flt(row.lr_slot_capacity) > 0:
		occupied = flt(frappe.db.sql("SELECT COALESCE(SUM(actual_qty),0) FROM `tabBin` WHERE warehouse=%s", warehouse)[0][0])
		if occupied + flt(incoming_qty) > flt(row.lr_slot_capacity) + 0.001:
			frappe.throw(_("Location {0} has capacity {1}; occupied plus incoming would be {2}.").format(
				warehouse, row.lr_slot_capacity, occupied + flt(incoming_qty)
			))


def _append_movement(pkg, movement_type, qty, source, target, ref_dt, ref_name, ref_row=None):
	pkg.append(
		"movements",
		{
			"movement_type": movement_type,
			"qty": qty,
			"from_warehouse": source,
			"to_warehouse": target,
			"reference_doctype": ref_dt,
			"reference_name": ref_name,
			"reference_row": ref_row,
			"scanned_on": now_datetime(),
			"scanned_by": frappe.session.user,
		},
	)


def _reverse_movements(pkg, ref_dt, ref_name, ref_row=None):
	for row in pkg.movements:
		if row.reference_doctype == ref_dt and row.reference_name == ref_name and (
			not ref_row or row.reference_row == ref_row
		):
			row.is_reversed = 1


def _package_payload(pkg):
	return {
		"name": pkg.name,
		"barcode": pkg.barcode_value,
		"item_code": pkg.item_code,
		"item_name": pkg.item_name,
		"batch_no": pkg.batch_no,
		"received_qty": pkg.received_qty,
		"accepted_qty": pkg.accepted_qty,
		"remaining_qty": pkg.remaining_qty,
		"uom": pkg.stock_uom,
		"status": pkg.status,
		"current_warehouse": pkg.current_warehouse,
	}
