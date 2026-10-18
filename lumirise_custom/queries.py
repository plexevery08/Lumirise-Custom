"""Link-field search queries for the Sales Platform forms."""

import json

import frappe
from frappe.desk.reportview import get_match_cond


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def quotable_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Sales items backed by either a positive base-price row or costed Parent BOM."""
	frappe.has_permission("Item", "read", throw=True)
	filters = filters or {}
	conditions = (
		""
		if not filters.get("item_group")
		else "AND `tabItem`.item_group = %(item_group)s"
	)
	return frappe.db.sql(
		"""
		SELECT DISTINCT `tabItem`.name, `tabItem`.item_name, `tabItem`.item_group
		FROM `tabItem`
		LEFT JOIN `tabLumirise Base Price` base_price
		  ON base_price.item = `tabItem`.name AND base_price.price > 0
		LEFT JOIN `tabBOM` bom
		  ON bom.item = `tabItem`.name
		 AND bom.is_active = 1
		 AND bom.docstatus = 1
		 AND bom.custom_bom_type = 'Parent BOM'
		 AND (bom.custom_bom_cost > 0 OR bom.custom_1k_moq_price > 0)
		WHERE `tabItem`.disabled = 0
		  AND `tabItem`.is_sales_item = 1
		  AND (`tabItem`.name LIKE %(txt)s OR `tabItem`.item_name LIKE %(txt)s)
		  AND (base_price.name IS NOT NULL OR bom.name IS NOT NULL)
		  {conditions}
		  {match}
		ORDER BY `tabItem`.item_group, `tabItem`.item_name, `tabItem`.name
		LIMIT %(page_len)s OFFSET %(start)s
		""".format(
			conditions=conditions,
			match=get_match_cond("Item"),
		),
		{
			"txt": f"%{txt}%",
			"item_group": filters.get("item_group"),
			"start": start,
			"page_len": page_len,
		},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def master_box_finish_query(doctype, txt, searchfield, start, page_len, filters):
	"""Box Finishes that actually have Master Box Pricing records."""
	filters = filters or {}
	items = filters.get("items") or ([filters.get("item")] if filters.get("item") else [])
	if isinstance(items, str):
		items = json.loads(items)
	item_condition = ""
	values = {"txt": f"%{txt}%", "start": start, "page_len": page_len}
	if items:
		item_condition = "AND `tabMaster Box Pricing`.item IN %(items)s"
		values["items"] = tuple(items)
	return frappe.db.sql(
		"""
		SELECT DISTINCT `tabMaster Box Pricing`.box_finish
		FROM `tabMaster Box Pricing`
		WHERE `tabMaster Box Pricing`.box_finish LIKE %(txt)s
		  {item_condition}
		  {match}
		ORDER BY `tabMaster Box Pricing`.box_finish
		LIMIT %(page_len)s OFFSET %(start)s
		""".format(
			item_condition=item_condition,
			match=get_match_cond("Master Box Pricing"),
		),
		values,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def mono_box_finish_query(doctype, txt, searchfield, start, page_len, filters):
	"""Box Finishes priced for the given items (falls back to all priced finishes)."""
	items = (filters or {}).get("items") or []
	if isinstance(items, str):
		items = json.loads(items)

	conditions = "mbp.box_finish LIKE %(txt)s"
	values = {"txt": f"%{txt}%", "start": start, "page_len": page_len}
	if items:
		conditions += " AND mbp.item IN %(items)s"
		values["items"] = tuple(items)

	return frappe.db.sql(
		f"""
		SELECT DISTINCT mbp.box_finish
		FROM `tabMono Box Pricing` mbp
		WHERE {conditions}
		ORDER BY mbp.box_finish
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		values,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def line_warehouse_query(doctype, txt, searchfield, start, page_len, filters):
	"""Constrain a Warehouse Link to just the warehouses configured as production
	lines under Operations Settings → Production Lines. Lets the "Production Line"
	field be a real, openable Warehouse master (no more "document not found" from
	Link-ing at a child table) while keeping that child table the single config
	source."""
	settings = frappe.get_cached_doc("Lumirise Operations Settings")
	line_whs = [r.line_warehouse for r in settings.production_lines if r.line_warehouse and r.is_active]
	if not line_whs:
		return []
	return frappe.db.sql(
		"""
		SELECT name
		FROM `tabWarehouse`
		WHERE name IN %(whs)s
		  AND disabled = 0
		  AND name LIKE %(txt)s
		ORDER BY name
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{"whs": tuple(line_whs), "txt": f"%{txt}%", "start": start, "page_len": page_len},
	)
