"""Seed native Quality Inspection Parameters + two QI Templates (RM incoming and
FG in-house) from the Lumirise Defect Code master, so inspectors pick from a
pre-loaded template instead of free-typing parameters. Idempotent + fail-safe;
uses the standard ERPNext Quality Inspection doctypes (borrow before build)."""

import frappe

# Which defect codes belong on each template (by category fit).
RM_INCOMING = ["HV", "IR", "ECT", "CCL", "IPR", "WSZ", "VRG", "BISR", "MARK", "VIS", "DIM"]
FG_INHOUSE = ["HV", "IR", "IPR", "VRG", "PWR", "PF", "LEF", "CCT", "CRI", "VIS", "DIM", "DROP", "BISR", "MARK"]

TEMPLATES = [
	("Lumirise RM Incoming", RM_INCOMING),
	("Lumirise FG In-House", FG_INHOUSE),
]


def _ensure_param_group(category):
	"""parameter_group is a Link to Quality Inspection Parameter Group — create the
	group if it doesn't exist yet. Returns the group name, or None."""
	if not category or not frappe.db.exists("DocType", "Quality Inspection Parameter Group"):
		return None
	if not frappe.db.exists("Quality Inspection Parameter Group", category):
		try:
			frappe.get_doc({
				"doctype": "Quality Inspection Parameter Group",
				"group_name": category,
			}).insert(ignore_permissions=True)
		except Exception:
			return None
	return category


def _ensure_qi_parameter(defect):
	"""Create a Quality Inspection Parameter for a defect code if missing.
	Returns the parameter name, or None if the doctype is unavailable."""
	if not frappe.db.exists("DocType", "Quality Inspection Parameter"):
		return None
	param_name = defect.parameter[:140]
	if frappe.db.exists("Quality Inspection Parameter", param_name):
		return param_name
	doc = frappe.new_doc("Quality Inspection Parameter")
	# field name differs by version: 'parameter' (v13/14) holds the value.
	if doc.meta.has_field("parameter"):
		doc.parameter = param_name
	group = _ensure_param_group(defect.category)
	if group and doc.meta.has_field("parameter_group"):
		doc.parameter_group = group
	if doc.meta.has_field("description"):
		doc.description = f"{defect.defect_code} · class {defect.defect_class} · {defect.test_reference or ''}".strip()
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_template(template_name, defect_codes):
	if not frappe.db.exists("DocType", "Quality Inspection Template"):
		return
	if frappe.db.exists("Quality Inspection Template", template_name):
		return
	tmpl = frappe.new_doc("Quality Inspection Template")
	tmpl.quality_inspection_template_name = template_name
	for code in defect_codes:
		defect = frappe.db.get_value(
			"Lumirise Defect Code", code,
			["parameter", "defect_class", "category", "test_reference"], as_dict=True)
		if not defect:
			continue
		defect["defect_code"] = code
		defect = frappe._dict(defect)
		param = _ensure_qi_parameter(defect)
		if not param:
			continue
		row = {}
		# the child fieldname for the linked parameter is 'specification'.
		row["specification"] = param
		row["value"] = f"As per {defect.test_reference or 'IS spec'} (class {defect.defect_class})"
		tmpl.append("item_quality_inspection_parameter", row)
	if not tmpl.get("item_quality_inspection_parameter"):
		return
	tmpl.insert(ignore_permissions=True)


def seed_quality_templates():
	try:
		if not frappe.db.exists("DocType", "Lumirise Defect Code"):
			return
		for template_name, codes in TEMPLATES:
			_ensure_template(template_name, codes)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "seed_quality_templates failed")
