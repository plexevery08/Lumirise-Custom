"""Idempotent seed for the line-aware production → dispatch flow.

Runs on after_migrate (and can be run standalone via `bench execute`). Creates:
  * the operational warehouses the flow needs (Shop Floor, Production FG, Dispatch
    FG, Customer PDI, RM Rejection) and a "Production Lines" group with Line-1..3,
  * the Focus-named custom Stock Entry Types the handoff chain references,
  * Manufacturing Settings backflush mode = "Material Transferred for Manufacture"
    (so a Manufacture entry consumes RM from whichever line it was transferred to),
  * fills the new Lumirise Operations Settings warehouse fields + the per-line table.

Everything here is safe to run repeatedly. Nothing is created if it already exists.
"""

import frappe

# Custom Stock Entry Types -> native purpose. These give the operator the Focus 9
# screen names while staying on standard ERPNext stock mechanics underneath.
# is_standard stays 0 so they never collide with native set_stock_entry_type().
STOCK_ENTRY_TYPES = [
	("Material Issue to Shop Floor", "Material Transfer"),
	("Internal Stock Transfer to Line", "Material Transfer for Manufacture"),
	("Receipt from Production", "Manufacture"),
	("FG to Dispatch Transfer", "Material Transfer"),
]

# Warehouses the flow needs (always created). (warehouse name, is_group)
CORE_WAREHOUSES = [
	("Shop Floor", 0),
	("Production FG", 0),
	("Dispatch FG", 0),
	("Customer PDI", 0),
	("RM Rejection", 0),
]

# Simple "create if blank" mapping for the fields with no legacy ambiguity.
SIMPLE_WH_FIELDS = [
	("shop_floor_warehouse", "Shop Floor"),
	("pdi_warehouse", "Customer PDI"),
	("rejection_warehouse", "RM Rejection"),
]

LINE_GROUP = "Production Lines"
DEMO_LINES = ["Line-1", "Line-2", "Line-3"]


def setup_production_flow():
	"""Entry point — seed everything. Idempotent."""
	company, abbr = _company_and_abbr()
	if not company:
		return
	_seed_core_warehouses(company, abbr)
	line_warehouses = _seed_line_warehouses(company, abbr)
	_seed_stock_entry_types()
	_set_backflush_mode()
	_fill_operations_settings(company, abbr, line_warehouses)


def _company_and_abbr():
	import erpnext

	company = None
	if frappe.db.exists("DocType", "Lumirise Operations Settings"):
		company = frappe.db.get_single_value("Lumirise Operations Settings", "company")
	company = company or erpnext.get_default_company()
	if not company:
		return None, None
	abbr = frappe.db.get_value("Company", company, "abbr")
	return company, abbr


def _wh_name(name, abbr):
	return f"{name} - {abbr}" if abbr else name


def _ensure_warehouse(name, company, abbr, is_group=0, parent=None):
	"""Create a Warehouse if its resolved name doesn't already exist. Returns the
	full warehouse name."""
	full = _wh_name(name, abbr)
	if frappe.db.exists("Warehouse", full):
		return full
	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": name,
			"company": company,
			"is_group": is_group,
		}
	)
	if parent:
		doc.parent_warehouse = parent
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _seed_core_warehouses(company, abbr):
	for name, is_group in CORE_WAREHOUSES:
		_ensure_warehouse(name, company, abbr, is_group=is_group)


def _seed_line_warehouses(company, abbr):
	"""Create the Production Lines group + the demo line warehouses under it.
	Returns [(line_name, full_warehouse_name), ...]."""
	group = _ensure_warehouse(LINE_GROUP, company, abbr, is_group=1)
	out = []
	for line in DEMO_LINES:
		full = _ensure_warehouse(line, company, abbr, is_group=0, parent=group)
		out.append((line, full))
	return out


def _seed_stock_entry_types():
	for name, purpose in STOCK_ENTRY_TYPES:
		if frappe.db.exists("Stock Entry Type", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Stock Entry Type",
				"__newname": name,
				"purpose": purpose,
				"is_standard": 0,
			}
		).insert(ignore_permissions=True)


def _set_backflush_mode():
	"""Consume RM from the line it was transferred into (not a generic WIP)."""
	current = frappe.db.get_single_value(
		"Manufacturing Settings", "backflush_raw_materials_based_on"
	)
	if current != "Material Transferred for Manufacture":
		s = frappe.get_single("Manufacturing Settings")
		s.backflush_raw_materials_based_on = "Material Transferred for Manufacture"
		s.flags.ignore_permissions = True
		s.save(ignore_permissions=True)


def _fill_operations_settings(company, abbr, line_warehouses):
	if not frappe.db.exists("DocType", "Lumirise Operations Settings"):
		return
	s = frappe.get_single("Lumirise Operations Settings")
	changed = False
	if not s.company:
		s.company = company
		changed = True

	# Unambiguous fields: set to the dedicated warehouse if still blank.
	for field, name in SIMPLE_WH_FIELDS:
		if not s.get(field):
			s.set(field, _wh_name(name, abbr))
			changed = True

	# Two-FG split. Legacy builds used a single "Finished Goods" warehouse for the
	# old fg_warehouse — semantically that was the dispatch/PDI source. So:
	#   * dispatch_fg_warehouse -> the existing Finished Goods warehouse if present,
	#     else the dedicated "Dispatch FG".
	#   * fg_warehouse (Production FG) -> dedicated "Production FG" when blank OR
	#     when it still points at that legacy Finished Goods warehouse.
	legacy_fg = s.get("fg_warehouse")
	is_legacy_single_fg = legacy_fg and "finished goods" in legacy_fg.lower()
	if not s.get("dispatch_fg_warehouse"):
		standard_fg = frappe.db.get_value(
			"Warehouse",
			{"name": ["like", "%Finished Goods%"], "is_group": 0, "company": company},
			"name",
		)
		s.dispatch_fg_warehouse = standard_fg or _wh_name("Dispatch FG", abbr)
		changed = True
	if not legacy_fg or is_legacy_single_fg:
		s.fg_warehouse = _wh_name("Production FG", abbr)
		changed = True

	# Populate the per-line table once (only if empty).
	if not s.production_lines:
		for line_name, full in line_warehouses:
			s.append(
				"production_lines",
				{"line_name": line_name, "line_warehouse": full, "is_active": 1},
			)
		changed = True

	if changed:
		s.flags.ignore_permissions = True
		s.save(ignore_permissions=True)
