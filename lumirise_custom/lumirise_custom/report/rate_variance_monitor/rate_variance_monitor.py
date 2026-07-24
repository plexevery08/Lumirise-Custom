# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Rate Variance Monitor (Phase-2 point 26):
#   FG rows: Costing Rate = default BOM cost per unit (the planned/costed rate)
#            Actual Rate  = latest Manufacture receipt valuation (what production
#                           actually cost) -> RED when actual exceeds costing.
#   RM rows: Costing Rate = RM Price Book reference (preferred row, else cheapest)
#            Actual Rate  = latest submitted Purchase Receipt rate (company currency).
# One report, one rule: red = you paid/produced above the costed rate.

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	data = []
	if (filters.get("view") or "Both") in ("Both", "Finished Goods"):
		data += _fg_rows(filters)
	if (filters.get("view") or "Both") in ("Both", "Raw Materials"):
		data += _rm_rows(filters)
	if filters.get("exceeded_only"):
		data = [d for d in data if d["exceeded"]]
	return _columns(), data


def _columns():
	return [
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 170},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "kind", "label": _("Type"), "fieldtype": "Data", "width": 90},
		{"fieldname": "costing_rate", "label": _("Costing Rate"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "costing_source", "label": _("Costing Source"), "fieldtype": "Data", "width": 160},
		{"fieldname": "actual_rate", "label": _("Actual Rate"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "actual_source", "label": _("Actual Source"), "fieldtype": "Data", "width": 170},
		{"fieldname": "variance", "label": _("Variance"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "variance_pct", "label": _("Variance %"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "exceeded", "label": _("Exceeded"), "fieldtype": "Check", "width": 80},
	]


def _row(item_code, item_name, kind, costing, costing_src, actual, actual_src):
	variance = flt(actual) - flt(costing)
	return {
		"item_code": item_code, "item_name": item_name, "kind": kind,
		"costing_rate": flt(costing), "costing_source": costing_src,
		"actual_rate": flt(actual), "actual_source": actual_src,
		"variance": variance,
		"variance_pct": (variance / flt(costing) * 100) if flt(costing) else 0,
		"exceeded": 1 if (flt(costing) and variance > 0.005) else 0,
	}


def _fg_rows(filters):
	"""Every item with a default BOM = a produced item. Costing = BOM unit cost."""
	boms = frappe.db.sql(
		"""SELECT i.name item_code, i.item_name, b.name bom,
		          (b.total_cost / NULLIF(b.quantity, 0)) unit_cost
		   FROM `tabItem` i JOIN `tabBOM` b ON b.name = i.default_bom
		   WHERE i.disabled = 0""",
		as_dict=True,
	)
	if not boms:
		return []
	# latest actual manufacture rate per FG (finished line of a submitted Manufacture SE)
	actual = {}
	for r in frappe.db.sql(
		"""SELECT sed.item_code, sed.valuation_rate
		   FROM `tabStock Entry Detail` sed
		   JOIN `tabStock Entry` se ON se.name = sed.parent
		   WHERE se.docstatus = 1 AND se.purpose = 'Manufacture'
		     AND sed.is_finished_item = 1
		   ORDER BY se.posting_date ASC, se.posting_time ASC""",
		as_dict=True,
	):
		actual[r.item_code] = flt(r.valuation_rate)  # ascending -> last write = latest

	rows = []
	for b in boms:
		act = actual.get(b.item_code)
		if act is None and filters.get("with_actuals_only"):
			continue
		rows.append(_row(
			b.item_code, b.item_name, "FG",
			b.unit_cost, f"BOM {b.bom}",
			act or 0, "Last Manufacture receipt" if act is not None else "No production yet",
		))
	return rows


def _rm_rows(filters):
	"""Purchased items: Price Book reference vs latest actual purchase rate."""
	book = {}
	for r in frappe.db.sql(
		"""SELECT i.item_code, i.item_name, i.base_rate, i.preferred
		   FROM `tabRM Price Book Item` i
		   JOIN `tabRM Price Book` p ON p.name = i.parent
		   ORDER BY i.preferred ASC, i.base_rate DESC""",
		as_dict=True,
	):
		# order: non-preferred first, expensive first -> the LAST write per item is
		# the preferred row if one exists, else the cheapest rate.
		book[r.item_code] = r

	if not book:
		return []

	last_pr = {}
	for r in frappe.db.sql(
		"""SELECT pri.item_code, pri.base_rate, pr.name
		   FROM `tabPurchase Receipt Item` pri
		   JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
		   WHERE pr.docstatus = 1
		   ORDER BY pr.posting_date ASC, pr.posting_time ASC""",
		as_dict=True,
	):
		last_pr[r.item_code] = r  # last write = latest receipt

	rows = []
	for item_code, ref in book.items():
		pr = last_pr.get(item_code)
		if pr is None and filters.get("with_actuals_only"):
			continue
		rows.append(_row(
			item_code, ref.item_name, "RM",
			ref.base_rate, "RM Price Book" + (" (preferred)" if ref.preferred else ""),
			pr.base_rate if pr else 0,
			f"Last GRN {pr.name}" if pr else "No purchase yet",
		))
	return rows
