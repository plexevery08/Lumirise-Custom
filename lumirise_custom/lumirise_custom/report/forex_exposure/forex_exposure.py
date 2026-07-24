# Forex Exposure — per foreign currency: what Lumirise owes (open import POs +
# unpaid foreign Purchase Invoices) vs what is hedged (active Hedge Contracts),
# the net uncovered exposure, and mark-to-market on the hedges.
#
# Informational only — no GL posting; realised forex gain/loss stays with the
# native Exchange Gain/Loss account.

import frappe
from frappe import _
from frappe.utils import flt, nowdate


def _current_rate(currency):
	return flt(frappe.db.get_value(
		"Currency Exchange",
		{"from_currency": currency, "to_currency": "INR"},
		"exchange_rate", order_by="date desc")) or 0


def execute(filters=None):
	company_currency = frappe.get_cached_value(
		"Company", frappe.defaults.get_global_default("company"), "default_currency") or "INR"

	po = frappe.db.sql(
		"""select po.currency, sum((poi.qty - ifnull(poi.received_qty, 0)) * poi.rate) as amt
		from `tabPurchase Order` po join `tabPurchase Order Item` poi on poi.parent = po.name
		where po.docstatus = 1 and po.currency != %s and po.status not in ('Closed', 'Completed')
		group by po.currency""", (company_currency,), as_dict=True)
	pi = frappe.db.sql(
		"""select currency, sum(outstanding_amount) as amt from `tabPurchase Invoice`
		where docstatus = 1 and currency != %s and outstanding_amount > 0
		group by currency""", (company_currency,), as_dict=True)
	hedges = frappe.db.sql(
		"""select currency, sum(hedged_amount - ifnull(utilised_amount, 0)) as amt,
			sum((hedged_amount - ifnull(utilised_amount, 0)) * booked_rate) as booked_value
		from `tabHedge Contract`
		where docstatus = 1 and status = 'Active' and maturity_date >= %s
		group by currency""", (nowdate(),), as_dict=True)

	currencies = sorted({r.currency for r in po} | {r.currency for r in pi} | {r.currency for r in hedges})
	po_m = {r.currency: flt(r.amt) for r in po}
	pi_m = {r.currency: flt(r.amt) for r in pi}
	h_amt = {r.currency: flt(r.amt) for r in hedges}
	h_val = {r.currency: flt(r.booked_value) for r in hedges}

	rows = []
	for c in currencies:
		exposure = po_m.get(c, 0) + pi_m.get(c, 0)
		hedged = h_amt.get(c, 0)
		avg_booked = (h_val.get(c, 0) / hedged) if hedged else 0
		cur_rate = _current_rate(c)
		rows.append({
			"currency": c,
			"open_po_exposure": po_m.get(c, 0),
			"unpaid_pi_exposure": pi_m.get(c, 0),
			"total_exposure": exposure,
			"hedged": hedged,
			"net_uncovered": exposure - hedged,
			"avg_booked_rate": avg_booked,
			"current_rate": cur_rate,
			"mtm_gain_loss": (cur_rate - avg_booked) * hedged if hedged and cur_rate else 0,
		})
	columns = [
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 90},
		{"label": _("Open PO Exposure"), "fieldname": "open_po_exposure", "fieldtype": "Float", "width": 130},
		{"label": _("Unpaid PI Exposure"), "fieldname": "unpaid_pi_exposure", "fieldtype": "Float", "width": 135},
		{"label": _("Total Exposure"), "fieldname": "total_exposure", "fieldtype": "Float", "width": 120},
		{"label": _("Hedged (open)"), "fieldname": "hedged", "fieldtype": "Float", "width": 115},
		{"label": _("Net Uncovered"), "fieldname": "net_uncovered", "fieldtype": "Float", "width": 120},
		{"label": _("Avg Booked Rate"), "fieldname": "avg_booked_rate", "fieldtype": "Float", "width": 125},
		{"label": _("Current Rate"), "fieldname": "current_rate", "fieldtype": "Float", "width": 105},
		{"label": _("MTM Gain/Loss (INR)"), "fieldname": "mtm_gain_loss", "fieldtype": "Currency", "width": 145},
	]
	return columns, rows
