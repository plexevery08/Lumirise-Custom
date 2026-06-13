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
