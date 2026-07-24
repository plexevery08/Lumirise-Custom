# Costing Rate Breach — red-flags items whose real-world cost has crossed the
# costing-sheet rate (Phase-2 point 26, paid).
#
# One row per item that carries a default BOM with a computed costing rate
# (BOM.custom_bom_cost from the costing chain). Compared against:
#   - current valuation rate (Item.valuation_rate, falling back to Bin average)
#   - latest purchase rate (most recent submitted Purchase Receipt line;
#     falls back to latest submitted Purchase Invoice line)
# Breach % = (max(valuation, purchase) - costing) / costing.
# Indicator: red = over costing rate, amber = within 5% below, green otherwise.

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = frappe.db.sql(
		"""
		select
			b.item as item_code, b.item_name, b.name as bom,
			b.custom_bom_cost as costing_rate,
			i.valuation_rate,
			(select pri.rate from `tabPurchase Receipt Item` pri
			 join `tabPurchase Receipt` pr on pr.name = pri.parent
			 where pri.item_code = b.item and pr.docstatus = 1
			 order by pr.posting_date desc limit 1) as last_pr_rate,
			(select pii.rate from `tabPurchase Invoice Item` pii
			 join `tabPurchase Invoice` pi on pi.name = pii.parent
			 where pii.item_code = b.item and pi.docstatus = 1
			 order by pi.posting_date desc limit 1) as last_pi_rate
		from `tabBOM` b
		join `tabItem` i on i.name = b.item
		where b.docstatus = 1 and b.is_default = 1 and i.disabled = 0
			and ifnull(b.custom_bom_cost, 0) > 0
		""",
		as_dict=True)
	out = []
	for r in rows:
		r.purchase_rate = flt(r.last_pr_rate) or flt(r.last_pi_rate)
		actual = max(flt(r.valuation_rate), r.purchase_rate)
		r.actual_rate = actual
		r.breach_pct = ((actual - flt(r.costing_rate)) / flt(r.costing_rate) * 100) if r.costing_rate else 0
		if filters.get("only_breaches") and r.breach_pct <= 0:
			continue
		if actual > flt(r.costing_rate):
			r.indicator = "Red"
		elif r.costing_rate and actual >= flt(r.costing_rate) * 0.95:
			r.indicator = "Amber"
		else:
			r.indicator = "Green"
		out.append(r)
	out.sort(key=lambda r: -r.breach_pct)
	columns = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 280},
		{"label": _("BOM"), "fieldname": "bom", "fieldtype": "Link", "options": "BOM", "width": 160},
		{"label": _("Costing Rate"), "fieldname": "costing_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("Valuation Rate"), "fieldname": "valuation_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("Latest Purchase Rate"), "fieldname": "purchase_rate", "fieldtype": "Currency", "width": 140},
		{"label": _("Actual (max)"), "fieldname": "actual_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("Breach %"), "fieldname": "breach_pct", "fieldtype": "Percent", "width": 95},
		{"label": _("Signal"), "fieldname": "indicator", "fieldtype": "Data", "width": 80},
	]
	return columns, out
