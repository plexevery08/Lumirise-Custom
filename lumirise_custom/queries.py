"""Link-field search queries for the Sales Platform forms."""

import json

import frappe
from frappe.desk.reportview import get_match_cond


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def master_box_finish_query(doctype, txt, searchfield, start, page_len, filters):
	"""Box Finishes that actually have Master Box Pricing records."""
	return frappe.db.sql(
		"""
		SELECT DISTINCT mbp.box_finish
		FROM `tabMaster Box Pricing` mbp
		WHERE mbp.box_finish LIKE %(txt)s {match}
		ORDER BY mbp.box_finish
		LIMIT %(page_len)s OFFSET %(start)s
		""".format(match=get_match_cond("Master Box Pricing")),
		{"txt": f"%{txt}%", "start": start, "page_len": page_len},
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
