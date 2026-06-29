# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Lumirise Defect Code = the Quality defect master. Each inspection parameter is
# classified A (Critical) / B (Major) / C (Minor); that class selects which AQL
# (0.10 / 1.50 / 2.50) the AQL engine applies. Seeded once from the discovery-call
# spec; QA edits in-place (no code change) as the page-3/3 annexure is finalised.

import frappe
from frappe.model.document import Document


class LumiriseDefectCode(Document):
	pass


# 17-parameter seed from the discovery-call AQL spec. Class is a best-effort first
# pass (safety/electrical -> A, photometric/marking -> B, visual/dimensional -> C);
# QA confirms each against the IS:2500 annexure before go-live.
DEFECT_SEED = [
	("HV", "High-Voltage / Dielectric strength failure", "A", "Safety", "IS 10322 / IEC 60598"),
	("IR", "Insulation Resistance", "A", "Safety", "IS 10322"),
	("ECT", "Earth / Ground continuity (mounting CTC)", "A", "Safety", "IS 10322"),
	("BISR", "BIS-R marking / registration", "A", "Marking", "BIS-R"),
	("CCL", "Creepage & Clearance", "A", "Safety", "IEC 60598"),
	("WSZ", "Wire size / gauge", "B", "Electrical", "IS 694"),
	("VRG", "Voltage range / input", "B", "Electrical", "IEC 60598"),
	("LEF", "Lumen efficacy (lm/W)", "B", "Photometric", "IS 16102"),
	("CCT", "Correlated Colour Temperature", "B", "Photometric", "IS 16102"),
	("CRI", "Colour Rendering Index", "B", "Photometric", "IS 16102"),
	("IPR", "IP ingress-protection rating", "B", "Safety", "IS 60529"),
	("PWR", "Power / wattage tolerance", "B", "Electrical", "IS 16102"),
	("PF", "Power factor", "B", "Electrical", "IS 16102"),
	("DROP", "Drop / mechanical impact", "C", "Dimensional", "IEC 60598"),
	("VIS", "Visual / cosmetic defect", "C", "Visual", "In-house"),
	("DIM", "Dimensional deviation", "C", "Dimensional", "In-house"),
	("MARK", "Marking / label legibility", "C", "Marking", "IS 16102"),
]


def seed_defect_codes():
	"""Idempotent: insert any missing seed defect codes. Never overwrites a row QA
	has already edited (only creates the ones that don't exist yet)."""
	created = 0
	for code, parameter, cls, category, ref in DEFECT_SEED:
		if frappe.db.exists("Lumirise Defect Code", code):
			continue
		frappe.get_doc({
			"doctype": "Lumirise Defect Code",
			"defect_code": code,
			"parameter": parameter,
			"defect_class": cls,
			"category": category,
			"test_reference": ref,
			"applies_to": "Both",
			"is_active": 1,
		}).insert(ignore_permissions=True)
		created += 1
	return created
