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
		value = json.loads(value)
	if isinstance(value, dict):
		return [value]
	if value is None:
		return []
	if not isinstance(value, list):
		frappe.throw(_("Packages must be supplied as a list."))
	return value


def _clean_code(value, length=36):
	return re.sub(r"[^A-Za-z0-9-]+", "-", value or "").strip("-")[:length]


def _insert_package(values):
	"""Create package records only through this service-controlled path."""
	doc = frappe.get_doc(values)
	doc.flags.rm_barcode_system_update = True
	doc.insert(ignore_permissions=True)
	return doc


def _po_item_info(purchase_order, item_code):
	"""Return the single PO row's UOM conversion used by package quantities.

	Package quantities are always held in the Item stock UOM. The legacy inbound
	and IQC grids use the PO UOM, so their quantities must cross this boundary
	through the PO conversion factor.
	"""
	rows = frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order, "parenttype": "Purchase Order", "item_code": item_code},
		fields=["uom", "stock_uom", "conversion_factor"],
	)
	if len(rows) != 1:
		frappe.throw(
			_(
				"Purchase Order {0} must contain exactly one row for item {1} before RM labels are generated."
			).format(purchase_order, item_code)
		)
	row = rows[0]
	factor = flt(row.conversion_factor)
	if factor <= 0:
		frappe.throw(
			_("Invalid UOM conversion factor for item {0} on Purchase Order {1}.").format(
				item_code, purchase_order
			)
		)
	return frappe._dict(purchase_uom=row.uom, stock_uom=row.stock_uom, conversion_factor=factor)


def _is_descendant(warehouse, parent):
	if not warehouse or not parent:
		return False
	if warehouse == parent:
		return True
	bounds = frappe.db.get_value("Warehouse", parent, ["lft", "rgt"], as_dict=True)
	child = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=True)
	return bool(bounds and child and child.lft > bounds.lft and child.rgt < bounds.rgt)


def _lock_warehouse(warehouse):
	if warehouse:
		frappe.db.sql("SELECT name FROM `tabWarehouse` WHERE name=%s FOR UPDATE", warehouse)


def _get_or_create_batch(item_code, inbound, supplier_lot=None, manufacturing_date=None, expiry_date=None):
	if not frappe.db.get_value("Item", item_code, "has_batch_no"):
		if config.flag("require_batch_for_rm_packages", default=True):
			frappe.throw(
				_("Item {0} must have Has Batch No enabled before package labels are generated.").format(
					item_code
				)
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
	frappe.db.sql("SELECT name FROM `tabInbound Logistics` WHERE name=%s FOR UPDATE", inbound_logistics)
	log = frappe.get_doc("Inbound Logistics", inbound_logistics)
	if log.docstatus != 1 or log.status != "Reached Warehouse":
		frappe.throw(_("Submit the Inbound Logistics and mark it Reached Warehouse first."))
	submitted_iqc = frappe.db.get_value("IQC", {"inbound_logistics": log.name, "docstatus": 1}, "name")
	if submitted_iqc:
		frappe.throw(
			_("IQC {0} is already submitted; package labels can no longer be added.").format(submitted_iqc)
		)
	draft_iqc = frappe.db.get_value("IQC", {"inbound_logistics": log.name, "docstatus": 0}, "name")

	available = defaultdict(float)
	item_info = {}
	for row in log.items:
		if row.item_code not in item_info:
			item_info[row.item_code] = _po_item_info(log.purchase_order, row.item_code)
		info = item_info[row.item_code]
		available[row.item_code] += flt(row.qty) * info.conversion_factor
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
			frappe.throw(
				_("Package count and total quantity must be greater than zero for {0}.").format(item)
			)
		if already[item] + total > available[item] + 0.001:
			frappe.throw(
				_(
					"Package quantity for {0} exceeds the inbound quantity still available for labelling."
				).format(item)
			)

		batch = _get_or_create_batch(
			item, log.name, spec.get("supplier_lot"), spec.get("manufacturing_date"), spec.get("expiry_date")
		)
		base = flt(total / count, 6)
		assigned = 0.0
		for index in range(1, count + 1):
			qty = flt(total - assigned, 6) if index == count else base
			pkg = _insert_package(
				{
					"doctype": PACKAGE_DT,
					"inbound_logistics": log.name,
					"purchase_order": log.purchase_order,
					"iqc": draft_iqc,
					"item_code": item,
					"purchase_uom": item_info[item].purchase_uom,
					"conversion_factor": item_info[item].conversion_factor,
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
			)
			_append_movement(pkg, "Received", qty, None, None, "Inbound Logistics", log.name)
			_system_save(pkg)
			created.append(pkg.name)
			assigned += qty
		already[item] += total

	return {"created": created, "print_format": "Lumirise RM Package Label"}


@frappe.whitelist()
def create_opening_packages(
	item_code, warehouse, batch_no, package_count, total_qty, stock_reconciliation=None
):
	"""Represent already-posted stock with LPNs without touching the stock ledger.

	System Manager only. The physical count and any quantity correction must be
	posted through Stock Reconciliation first; this endpoint only creates labels.
	"""
	_require_enabled()
	frappe.only_for("System Manager")
	count, total = cint(package_count), flt(total_qty)
	if count <= 0 or total <= 0:
		frappe.throw(_("Package count and total quantity must be greater than zero."))
	_lock_warehouse(warehouse)
	_validate_location(warehouse, item_code, 0)
	if batch_no and frappe.db.get_value("Batch", batch_no, "item") != item_code:
		frappe.throw(_("Batch {0} does not belong to item {1}.").format(batch_no, item_code))
	if config.flag("require_batch_for_rm_packages", default=True) and not batch_no:
		frappe.throw(_("Select the existing ERPNext Batch for opening stock."))
	if batch_no and not cint(frappe.db.get_value("Item", item_code, "has_batch_no")):
		frappe.throw(_("Item {0} is not batch-enabled.").format(item_code))
	bin_qty = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
	stock_qty = bin_qty
	if batch_no:
		from erpnext.stock.doctype.batch.batch import get_batch_qty

		stock_qty = flt(get_batch_qty(batch_no=batch_no, warehouse=warehouse, item_code=item_code))
	package_filters = ["item_code=%s", "current_warehouse=%s", "remaining_qty>0"]
	package_values = [item_code, warehouse]
	if batch_no:
		package_filters.append("batch_no=%s")
		package_values.append(batch_no)
	represented = flt(
		frappe.db.sql(
			f"""SELECT COALESCE(SUM(remaining_qty),0) FROM `tabRM Receiving Package`
		WHERE {" AND ".join(package_filters)}""",
			package_values,
		)[0][0]
	)
	if represented + total > stock_qty + 0.001:
		frappe.throw(
			_("Opening labels would represent {0}, but matching ERP stock in {1} is only {2}.").format(
				represented + total, warehouse, stock_qty
			)
		)

	created = []
	base, assigned = flt(total / count, 6), 0.0
	for index in range(1, count + 1):
		qty = flt(total - assigned, 6) if index == count else base
		pkg = _insert_package(
			{
				"doctype": PACKAGE_DT,
				"is_opening_stock": 1,
				"stock_reconciliation": stock_reconciliation,
				"item_code": item_code,
				"purchase_uom": frappe.db.get_value("Item", item_code, "stock_uom"),
				"conversion_factor": 1,
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
		)
		_append_movement(
			pkg,
			"Received",
			qty,
			None,
			warehouse,
			"Stock Reconciliation" if stock_reconciliation else None,
			stock_reconciliation,
		)
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
		if not row.iqc or cint(frappe.db.get_value("IQC", row.iqc, "docstatus")) == 2:
			frappe.db.set_value(PACKAGE_DT, row.name, "iqc", doc.name, update_modified=False)


@frappe.whitelist()
def record_package_qc(iqc, package_barcode, accepted_qty, rejected_qty=0):
	_require_enabled()
	frappe.has_permission("IQC", "write", iqc, throw=True)
	frappe.db.sql("SELECT name FROM `tabIQC` WHERE name=%s FOR UPDATE", iqc)
	doc = frappe.get_doc("IQC", iqc)
	if doc.docstatus != 0:
		frappe.throw(_("Package results can only be scanned while the IQC is in Draft."))
	if doc.status not in ("IQC Received", "Testing"):
		frappe.throw(_("Package results can only be scanned while IQC is Received or Testing."))
	pkg = _package_by_barcode(package_barcode, lock=True)
	if pkg.inbound_logistics != doc.inbound_logistics:
		frappe.throw(_("Package {0} does not belong to this inbound consignment.").format(pkg.name))
	if pkg.iqc and pkg.iqc != doc.name:
		frappe.throw(_("Package {0} is already linked to IQC {1}.").format(pkg.name, pkg.iqc))
	if pkg.status != "Pending IQC" or flt(pkg.accepted_qty) or flt(pkg.rejected_qty):
		frappe.throw(
			_(
				"Package {0} already has an IQC result. Use Reset Package Result before scanning it again."
			).format(pkg.name)
		)
	accepted, rejected = flt(accepted_qty), flt(rejected_qty)
	if accepted < 0 or rejected < 0 or abs((accepted + rejected) - flt(pkg.received_qty)) > 0.001:
		frappe.throw(
			_("Accepted plus rejected quantity must equal package quantity {0}.").format(pkg.received_qty)
		)
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
		rejected_package = _insert_package(
			{
				"doctype": PACKAGE_DT,
				"inbound_logistics": pkg.inbound_logistics,
				"iqc": doc.name,
				"purchase_order": pkg.purchase_order,
				"parent_package": pkg.name,
				"split_reason": "IQC Rejection",
				"item_code": pkg.item_code,
				"purchase_uom": pkg.purchase_uom,
				"conversion_factor": pkg.conversion_factor,
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
		)
		_append_movement(pkg, "Split", rejected, None, None, PACKAGE_DT, rejected_package.name)
		_append_movement(rejected_package, "Split", rejected, None, None, PACKAGE_DT, pkg.name)
		_system_save(rejected_package)
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


@frappe.whitelist()
def reset_package_qc(iqc, package_barcode):
	"""Clear one mistaken package result while the IQC is still a draft.

	Physical child packages created by a partial rejection remain separate labels;
	each can be reset and rescanned independently so the split audit is preserved.
	"""
	_require_enabled()
	frappe.has_permission("IQC", "write", iqc, throw=True)
	frappe.db.sql("SELECT name FROM `tabIQC` WHERE name=%s FOR UPDATE", iqc)
	doc = frappe.get_doc("IQC", iqc)
	if doc.docstatus != 0:
		frappe.throw(_("Package results can only be reset while the IQC is in Draft."))
	if doc.status not in ("IQC Received", "Testing"):
		frappe.throw(_("Package results can only be reset while IQC is Received or Testing."))
	pkg = _package_by_barcode(package_barcode, lock=True)
	if pkg.iqc != doc.name or pkg.inbound_logistics != doc.inbound_logistics:
		frappe.throw(_("Package {0} does not belong to IQC {1}.").format(pkg.name, doc.name))
	if pkg.purchase_receipt:
		frappe.throw(_("Package {0} is already linked to GRN {1}.").format(pkg.name, pkg.purchase_receipt))
	pkg.accepted_qty = 0
	pkg.rejected_qty = 0
	pkg.remaining_qty = 0
	pkg.status = "Pending IQC"
	pkg.last_scan_on = now_datetime()
	pkg.last_scan_by = frappe.session.user
	_system_save(pkg)
	_sync_iqc_totals(doc)
	return _package_payload(pkg)


def _sync_iqc_totals(iqc):
	totals = defaultdict(lambda: [0.0, 0.0])
	for pkg in frappe.get_all(
		PACKAGE_DT,
		{"iqc": iqc.name},
		["item_code", "accepted_qty", "rejected_qty", "conversion_factor"],
	):
		factor = flt(pkg.conversion_factor) or 1
		totals[pkg.item_code][0] += flt(pkg.accepted_qty) / factor
		totals[pkg.item_code][1] += flt(pkg.rejected_qty) / factor
	for row in iqc.items:
		if row.item_code in totals:
			accepted, rejected = totals[row.item_code]
			frappe.db.set_value(
				"IQC Item",
				row.name,
				{"accepted_qty": accepted, "rejected_qty": rejected},
				update_modified=False,
			)


def validate_iqc_packages(doc, method=None):
	frappe.db.sql("SELECT name FROM `tabInbound Logistics` WHERE name=%s FOR UPDATE", doc.inbound_logistics)
	package_fields = [
		"name",
		"item_code",
		"received_qty",
		"accepted_qty",
		"rejected_qty",
		"conversion_factor",
	]
	packages = frappe.get_all(
		PACKAGE_DT,
		{"inbound_logistics": doc.inbound_logistics},
		package_fields,
	)
	if not packages:
		return
	for package_name in sorted(pkg.name for pkg in packages):
		frappe.db.sql("SELECT name FROM `tabRM Receiving Package` WHERE name=%s FOR UPDATE", package_name)
	packages = frappe.get_all(PACKAGE_DT, {"inbound_logistics": doc.inbound_logistics}, package_fields)
	doc_items = [row.item_code for row in doc.items]
	if len(doc_items) != len(set(doc_items)):
		frappe.throw(_("Package-controlled IQC requires exactly one IQC row per item."))
	package_items = {pkg.item_code for pkg in packages}
	if package_items != set(doc_items):
		frappe.throw(_("IQC item rows must exactly match the labelled package items."))
	package_totals = defaultdict(lambda: [0.0, 0.0, 0.0])
	for pkg in packages:
		if abs(flt(pkg.received_qty) - flt(pkg.accepted_qty) - flt(pkg.rejected_qty)) > 0.001:
			frappe.throw(_("Scan a complete IQC result for package {0} before submitting.").format(pkg.name))
		factor = flt(pkg.conversion_factor) or 1
		package_totals[pkg.item_code][0] += flt(pkg.received_qty) / factor
		package_totals[pkg.item_code][1] += flt(pkg.accepted_qty) / factor
		package_totals[pkg.item_code][2] += flt(pkg.rejected_qty) / factor
	for row in doc.items:
		received, accepted, rejected = package_totals[row.item_code]
		if abs(received - flt(row.received_qty)) > 0.001:
			frappe.throw(
				_("Package labels for {0} total {1}, but IQC received quantity is {2}.").format(
					row.item_code, received, row.received_qty
				)
			)
		if abs(accepted - flt(row.accepted_qty)) > 0.001 or abs(rejected - flt(row.rejected_qty)) > 0.001:
			frappe.throw(
				_("IQC totals for {0} must come from the scanned package results.").format(row.item_code)
			)


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
		PACKAGE_DT,
		{"iqc": iqc.name},
		["name", "item_code", "batch_no", "accepted_qty", "rejected_qty", "conversion_factor"],
	)
	if not packages:
		return pr
	groups = defaultdict(lambda: {"accepted": 0.0, "rejected": 0.0, "packages": [], "factor": None})
	for pkg in packages:
		key = (pkg.item_code, pkg.batch_no or "")
		factor = flt(pkg.conversion_factor) or 1
		if groups[key]["factor"] not in (None, factor):
			frappe.throw(_("Package UOM conversions disagree for item {0} batch {1}.").format(*key))
		groups[key]["factor"] = factor
		groups[key]["accepted"] += flt(pkg.accepted_qty)
		groups[key]["rejected"] += flt(pkg.rejected_qty)
		groups[key]["packages"].append(pkg.name)

	source = {}
	source_counts = defaultdict(int)
	for row in pr.items:
		source.setdefault(row.item_code, row.as_dict())
		source_counts[row.item_code] += 1
	new_rows = []
	staging = config.receiving_warehouse()
	for (item, batch), values in groups.items():
		if item not in source:
			frappe.throw(_("No Purchase Order row was mapped for package item {0}.").format(item))
		if source_counts[item] > 1:
			frappe.throw(
				_(
					"Purchase Order has duplicate rows for {0}. Consolidate them before package GRN mapping."
				).format(item)
			)
		data = {
			key: value
			for key, value in source[item].items()
			if key not in {"name", "parent", "parenttype", "parentfield", "idx", "docstatus"}
		}
		factor = values["factor"] or flt(source[item].get("conversion_factor")) or 1
		accepted = values["accepted"] / factor
		rejected = values["rejected"] / factor
		if values["accepted"] and not staging:
			frappe.throw(_("Configure the Receiving / Staging warehouse before creating the GRN."))
		data.update(
			{
				"qty": accepted,
				"received_qty": accepted + rejected,
				"rejected_qty": rejected,
				"warehouse": staging or source[item].get("warehouse"),
				"rejected_warehouse": config.rejection_warehouse(required=True) if rejected else None,
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


def validate_grn_packages(doc, method=None):
	"""Make the GRN rows authoritative and prevent API/manual tampering."""
	enforce = config.flag("enforce_rm_package_scan", default=False)
	tracked_rows = [
		row for row in doc.items if cint(frappe.db.get_value("Item", row.item_code, "lr_rm_barcode_tracking"))
	]
	if not doc.get("lr_iqc"):
		if enforce and tracked_rows:
			frappe.throw(_("Tracked RM receipts must be created from a submitted IQC."))
		return
	iqc = frappe.get_doc("IQC", doc.lr_iqc)
	frappe.db.sql("SELECT name FROM `tabIQC` WHERE name=%s FOR UPDATE", iqc.name)
	iqc.reload()
	if iqc.docstatus != 1 or iqc.status not in ("Passed", "Moved to RM"):
		frappe.throw(_("Linked IQC {0} is not submitted and passed.").format(iqc.name))
	if doc.get("lr_inbound_logistics") != iqc.inbound_logistics:
		frappe.throw(_("GRN inbound reference does not match IQC {0}.").format(iqc.name))

	expected = set(frappe.get_all(PACKAGE_DT, {"iqc": iqc.name}, pluck="name"))
	if not expected:
		if enforce and tracked_rows:
			frappe.throw(_("Generate and scan RM package labels before submitting this tracked GRN."))
		return
	for package_name in sorted(expected):
		frappe.db.sql("SELECT name FROM `tabRM Receiving Package` WHERE name=%s FOR UPDATE", package_name)
	seen = set()
	for row in doc.items:
		accepted_stock = rejected_stock = 0.0
		for name in filter(None, (row.get("lr_rm_package_refs") or "").splitlines()):
			if name in seen:
				frappe.throw(_("RM package {0} appears on more than one GRN row.").format(name))
			seen.add(name)
			pkg = frappe.get_doc(PACKAGE_DT, name)
			if pkg.iqc != iqc.name or pkg.item_code != row.item_code:
				frappe.throw(_("RM package {0} does not match this GRN row/IQC.").format(name))
			if pkg.status not in ("IQC Passed", "Rejected"):
				frappe.throw(_("RM package {0} is not ready for GRN (status {1}).").format(name, pkg.status))
			if (pkg.batch_no or "") != (row.get("batch_no") or ""):
				frappe.throw(_("GRN batch does not match package {0}.").format(name))
			if pkg.purchase_receipt and pkg.purchase_receipt != doc.name:
				frappe.throw(
					_("RM package {0} is already received on {1}.").format(name, pkg.purchase_receipt)
				)
			accepted_stock += flt(pkg.accepted_qty)
			rejected_stock += flt(pkg.rejected_qty)
		factor = flt(row.conversion_factor) or 1
		if abs(accepted_stock - flt(row.qty) * factor) > 0.001:
			frappe.throw(
				_("GRN accepted quantity does not match its RM packages on row {0}.").format(row.idx)
			)
		if abs(rejected_stock - flt(row.rejected_qty) * factor) > 0.001:
			frappe.throw(
				_("GRN rejected quantity does not match its RM packages on row {0}.").format(row.idx)
			)
		if accepted_stock and row.warehouse != config.receiving_warehouse():
			frappe.throw(
				_("Accepted RM packages must first enter the configured Receiving / Staging warehouse.")
			)
		if rejected_stock and row.rejected_warehouse != config.rejection_warehouse(required=True):
			frappe.throw(_("Rejected RM packages must enter the configured rejection warehouse."))
	if seen != expected:
		frappe.throw(
			_("GRN package references do not exactly match all packages inspected by IQC {0}.").format(
				iqc.name
			)
		)


def on_grn_submit(doc, method=None):
	if not doc.get("lr_iqc"):
		return
	staging = config.receiving_warehouse()
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
			_append_movement(
				pkg,
				"GRN",
				pkg.accepted_qty or pkg.rejected_qty,
				None,
				pkg.current_warehouse,
				"Purchase Receipt",
				doc.name,
				row.name,
			)
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
	_lock_warehouse(location)
	if pkg.status != "Ready to Put Away":
		frappe.throw(
			_("Package {0} is not ready for put-away (current status: {1}).").format(pkg.name, pkg.status)
		)
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
	frappe.has_permission(PACKAGE_DT, "read", pkg.name, throw=True)
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
	child = _insert_package(
		{
			"doctype": PACKAGE_DT,
			"is_opening_stock": pkg.is_opening_stock,
			"inbound_logistics": pkg.inbound_logistics,
			"iqc": pkg.iqc,
			"purchase_order": pkg.purchase_order,
			"purchase_receipt": pkg.purchase_receipt,
			"purchase_receipt_item": pkg.purchase_receipt_item,
			"stock_reconciliation": pkg.stock_reconciliation,
			"parent_package": pkg.name,
			"split_reason": "Partial Issue",
			"item_code": pkg.item_code,
			"purchase_uom": pkg.purchase_uom,
			"conversion_factor": pkg.conversion_factor,
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
	)
	pkg.received_qty = flt(pkg.received_qty) - qty
	pkg.accepted_qty = flt(pkg.accepted_qty) - qty
	pkg.remaining_qty = flt(pkg.remaining_qty) - qty
	_append_movement(pkg, "Split", qty, pkg.current_warehouse, pkg.current_warehouse, PACKAGE_DT, child.name)
	_append_movement(child, "Split", qty, pkg.current_warehouse, pkg.current_warehouse, PACKAGE_DT, pkg.name)
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

	child = _insert_package(
		{
			"doctype": PACKAGE_DT,
			"inbound_logistics": pkg.inbound_logistics,
			"iqc": iqc.name,
			"purchase_order": pkg.purchase_order,
			"parent_package": pkg.name,
			"split_reason": "IQC Sample",
			"item_code": pkg.item_code,
			"purchase_uom": pkg.purchase_uom,
			"conversion_factor": pkg.conversion_factor,
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
	)
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
	package_names = sorted({row.lr_rm_package for row in doc.items if row.get("lr_rm_package")})
	for package_name in package_names:
		frappe.db.sql("SELECT name FROM `tabRM Receiving Package` WHERE name=%s FOR UPDATE", package_name)
	putaway_totals = defaultdict(float)
	if doc.stock_entry_type == PUTAWAY_TYPE:
		for row in doc.items:
			putaway_totals[row.t_warehouse] += flt(row.qty)
		for warehouse in sorted(filter(None, putaway_totals)):
			_lock_warehouse(warehouse)
	seen = defaultdict(float)
	for row in doc.items:
		tracked = cint(frappe.db.get_value("Item", row.item_code, "lr_rm_barcode_tracking"))
		from_rm = _is_descendant(row.s_warehouse, rm_root) if enforce else False
		package_stock = bool(
			enforce
			and row.s_warehouse
			and frappe.db.exists(
				PACKAGE_DT,
				{"item_code": row.item_code, "current_warehouse": row.s_warehouse, "remaining_qty": [">", 0]},
			)
		)
		if enforce and tracked and (from_rm or package_stock) and not row.get("lr_rm_package"):
			frappe.throw(
				_("Row {0} ({1}): scan the RM package barcode before submission.").format(
					row.idx, row.item_code
				)
			)
		if not row.get("lr_rm_package"):
			continue
		pkg = frappe.get_doc(PACKAGE_DT, row.lr_rm_package)
		if pkg.status in ("Pending IQC", "IQC Passed", "Rejected", "Consumed"):
			frappe.throw(
				_("Row {0}: package {1} cannot move while its status is {2}.").format(
					row.idx, pkg.name, pkg.status
				)
			)
		if pkg.item_code != row.item_code:
			frappe.throw(
				_("Row {0}: package {1} contains {2}, not {3}.").format(
					row.idx, pkg.name, pkg.item_code, row.item_code
				)
			)
		if pkg.current_warehouse != row.s_warehouse:
			frappe.throw(
				_("Row {0}: package {1} is in {2}, not {3}.").format(
					row.idx, pkg.name, pkg.current_warehouse, row.s_warehouse
				)
			)
		if pkg.batch_no and row.get("batch_no") != pkg.batch_no:
			frappe.throw(
				_("Row {0}: batch must be {1} for package {2}.").format(row.idx, pkg.batch_no, pkg.name)
			)
		if doc.stock_entry_type == PUTAWAY_TYPE:
			if pkg.status != "Ready to Put Away" or row.s_warehouse != config.receiving_warehouse():
				frappe.throw(
					_("Package {0} is not ready in Receiving / Staging for put-away.").format(pkg.name)
				)
			_validate_location(row.t_warehouse, row.item_code, putaway_totals[row.t_warehouse])
		elif pkg.status == "Ready to Put Away":
			is_sample = frappe.db.exists("IQC Sample", {"rm_package": pkg.name, "status": "Issued"})
			if row.t_warehouse != config.iqc_lab_warehouse() or not is_sample:
				frappe.throw(_("Package {0} must be put away by scanning an RM rack.").format(pkg.name))
		if doc.stock_entry_type == ISSUE_TYPE:
			shop_floor = config.shop_floor_warehouse()
			valid_target = (
				row.t_warehouse == shop_floor
				or _is_descendant(row.t_warehouse, shop_floor)
				or config.is_valid_line(row.t_warehouse)
			)
			if pkg.status != "Stored" or not valid_target:
				frappe.throw(
					_("Package {0} must move from an RM rack to a configured shop-floor location.").format(
						pkg.name
					)
				)
		seen[pkg.name] += flt(row.qty)
		if seen[pkg.name] > flt(pkg.remaining_qty) + 0.001:
			frappe.throw(_("Package {0} has only {1} remaining.").format(pkg.name, pkg.remaining_qty))
	for package_name, qty in seen.items():
		remaining = flt(frappe.db.get_value(PACKAGE_DT, package_name, "remaining_qty"))
		if abs(qty - remaining) > 0.001:
			frappe.throw(
				_(
					"Move the complete package {0}. The scanner will create a child label for a partial pick."
				).format(package_name)
			)


def validate_warehouse_location_barcode(doc, method=None):
	barcode = (doc.get("lr_location_barcode") or "").strip()
	if not barcode:
		return
	doc.lr_location_barcode = barcode
	duplicate = frappe.db.get_value(
		"Warehouse", {"lr_location_barcode": barcode, "name": ["!=", doc.name]}, "name"
	)
	if duplicate:
		frappe.throw(_("Location barcode {0} is already assigned to {1}.").format(barcode, duplicate))


def validate_stock_reconciliation_packages(doc, method=None):
	"""Prevent silent package/ledger drift once scan enforcement is live."""
	if not _enabled() or not config.flag("enforce_rm_package_scan", default=False):
		return
	rm_root = config.rm_warehouse()
	for row in doc.items:
		if not _is_descendant(row.warehouse, rm_root):
			continue
		if cint(frappe.db.get_value("Item", row.item_code, "lr_rm_barcode_tracking")):
			frappe.throw(
				_(
					"Row {0}: tracked RM stock cannot be reconciled while package-scan enforcement is on. "
					"Use an approved count window, disable enforcement, reconcile stock, update package labels, "
					"run the health check, then re-enable enforcement."
				).format(row.idx)
			)


def on_stock_entry_submit(doc, method=None):
	for row in doc.items:
		if not row.get("lr_rm_package"):
			continue
		pkg = _locked_package(row.lr_rm_package)
		if pkg.current_warehouse != row.s_warehouse:
			frappe.throw(
				_("Package {0} moved from {1} after this Stock Entry was prepared; scan it again.").format(
					pkg.name, row.s_warehouse
				)
			)
		if flt(row.qty) > flt(pkg.remaining_qty) + 0.001:
			frappe.throw(_("Package {0} no longer has enough remaining quantity.").format(pkg.name))
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
				pkg.status = (
					"Stored"
					if _is_descendant(pkg.current_warehouse, config.rm_warehouse())
					else "In Production"
				)
			movement = "Transfer"
		pkg.last_scan_on = now_datetime()
		pkg.last_scan_by = frappe.session.user
		_append_movement(
			pkg, movement, row.qty, row.s_warehouse, row.t_warehouse, "Stock Entry", doc.name, row.name
		)
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
	barcode = (barcode or "").strip()
	name = frappe.db.get_value(PACKAGE_DT, {"barcode_value": barcode}, "name") or (
		barcode if frappe.db.exists(PACKAGE_DT, barcode) else None
	)
	if not name:
		frappe.throw(_("Unknown RM package barcode: {0}").format(barcode))
	return _locked_package(name) if lock else frappe.get_doc(PACKAGE_DT, name)


def _warehouse_by_barcode(barcode):
	barcode = (barcode or "").strip()
	name = frappe.db.get_value("Warehouse", {"lr_location_barcode": barcode}, "name")
	if not name:
		frappe.throw(_("Unknown warehouse/location barcode: {0}").format(barcode))
	return name


def _validate_location(warehouse, item_code, incoming_qty):
	if not _is_descendant(warehouse, config.rm_warehouse()):
		frappe.throw(
			_("Location {0} is not inside the configured Raw Material Store hierarchy.").format(warehouse)
		)
	row = frappe.db.get_value(
		"Warehouse",
		warehouse,
		[
			"is_group",
			"disabled",
			"lr_location_barcode",
			"lr_slot_status",
			"lr_slot_capacity",
			"lr_slot_capacity_uom",
			"lr_allowed_item_group",
		],
		as_dict=True,
	)
	if not row or row.is_group or row.disabled:
		frappe.throw(_("Choose an enabled leaf warehouse/rack location."))
	if not row.lr_location_barcode:
		frappe.throw(_("Assign and print a Location Barcode for {0} before using it.").format(warehouse))
	if row.lr_slot_status and row.lr_slot_status != "Available":
		frappe.throw(_("Location {0} is {1}.").format(warehouse, row.lr_slot_status))
	if row.lr_allowed_item_group:
		group = frappe.db.get_value("Item", item_code, "item_group")
		if group != row.lr_allowed_item_group:
			frappe.throw(
				_("Location {0} only allows item group {1}.").format(warehouse, row.lr_allowed_item_group)
			)
	if row.lr_slot_capacity_uom:
		stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
		if stock_uom != row.lr_slot_capacity_uom:
			frappe.throw(
				_("Location {0} capacity is measured in {1}; item {2} uses {3}.").format(
					warehouse, row.lr_slot_capacity_uom, item_code, stock_uom
				)
			)
		mismatched_uom = frappe.db.sql(
			"""SELECT i.name FROM `tabBin` b
			JOIN `tabItem` i ON i.name=b.item_code
			WHERE b.warehouse=%s AND ABS(b.actual_qty)>0.001 AND i.stock_uom!=%s LIMIT 1""",
			(warehouse, row.lr_slot_capacity_uom),
		)
		if mismatched_uom:
			frappe.throw(
				_(
					"Location {0} contains stock with another UOM; its numeric capacity cannot be enforced."
				).format(warehouse)
			)
	if flt(row.lr_slot_capacity) > 0:
		occupied = flt(
			frappe.db.sql("SELECT COALESCE(SUM(actual_qty),0) FROM `tabBin` WHERE warehouse=%s", warehouse)[
				0
			][0]
		)
		if occupied + flt(incoming_qty) > flt(row.lr_slot_capacity) + 0.001:
			frappe.throw(
				_("Location {0} has capacity {1}; occupied plus incoming would be {2}.").format(
					warehouse, row.lr_slot_capacity, occupied + flt(incoming_qty)
				)
			)


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
		if (
			row.reference_doctype == ref_dt
			and row.reference_name == ref_name
			and (not ref_row or row.reference_row == ref_row)
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
