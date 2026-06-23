"""Daily Cash Flow -- the forward day-by-day treasury view Ajay asked for.

Ajay review 2026-06-14 (01:22:43-01:24:00): "we also need a customized report for
daily cash flow... on 2nd you'll have payables and receivables. If payables are 2
crores and receivables is only 50 lakhs, you are having a deficit of 50 lakhs..."
"It is simply in and out -- what is the input, what is the output, what is the
difference." This projects, per day from an opening bank balance, the receivables
due (in), payables due (out), the net difference, and the running closing balance,
so a shortfall is visible days ahead and funds can be arranged before it bites.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, add_days, add_months, nowdate, formatdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	company = filters.company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw(_("Select a Company."))
	from_date = getdate(filters.from_date or nowdate())
	to_date = getdate(filters.to_date or add_months(from_date, 1))
	if to_date < from_date:
		frappe.throw(_("To Date must be on or after From Date."))

	opening = _opening_balance(company, from_date)
	receivables = _due_by_day("Sales Invoice", company, from_date, to_date)
	payables = _due_by_day("Purchase Invoice", company, from_date, to_date)

	data = []
	running = opening
	day = from_date
	tot_in = tot_out = 0.0
	min_balance, min_day = running, from_date
	while day <= to_date:
		rin = flt(receivables.get(day, 0.0))
		rout = flt(payables.get(day, 0.0))
		net = rin - rout
		row_open = running
		running = running + net
		tot_in += rin
		tot_out += rout
		if running < min_balance:
			min_balance, min_day = running, day
		data.append({
			"cf_date": day,
			"opening": row_open,
			"receivable_in": rin,
			"payable_out": rout,
			"net_difference": net,
			"closing_balance": running,
		})
		day = add_days(day, 1)

	columns = [
		{"fieldname": "cf_date", "label": _("Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "opening", "label": _("Opening Balance"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "receivable_in", "label": _("Receivable In"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "payable_out", "label": _("Payable Out"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "net_difference", "label": _("Net (Difference)"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "closing_balance", "label": _("Closing Balance"), "fieldtype": "Currency", "width": 150},
	]

	chart = {
		"data": {
			"labels": [formatdate(r["cf_date"]) for r in data],
			"datasets": [{"name": _("Closing Balance"), "values": [r["closing_balance"] for r in data]}],
		},
		"type": "line",
	}

	report_summary = [
		{"label": _("Opening Balance"), "value": opening, "datatype": "Currency", "indicator": "Blue"},
		{"label": _("Total In"), "value": tot_in, "datatype": "Currency", "indicator": "Green"},
		{"label": _("Total Out"), "value": tot_out, "datatype": "Currency", "indicator": "Red"},
		{"label": _("Net"), "value": tot_in - tot_out, "datatype": "Currency",
		 "indicator": "Green" if (tot_in - tot_out) >= 0 else "Red"},
		{"label": _("Lowest Balance ({0})").format(formatdate(min_day)), "value": min_balance,
		 "datatype": "Currency", "indicator": "Red" if min_balance < 0 else "Green"},
	]

	message = None
	if min_balance < 0:
		message = _(
			"⚠ Projected cash shortfall: balance dips to {0} on {1}. Arrange funds "
			"before then to keep vendor commitments."
		).format(frappe.utils.fmt_money(min_balance), formatdate(min_day))

	return columns, data, message, chart, report_summary


def _opening_balance(company, as_of):
	"""Bank + Cash GL balance strictly before `as_of`."""
	accounts = frappe.get_all(
		"Account",
		filters={"company": company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0},
		pluck="name",
	)
	if not accounts:
		return 0.0
	row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(debit - credit), 0)
		FROM `tabGL Entry`
		WHERE company = %(company)s
		  AND account IN %(accounts)s
		  AND posting_date < %(as_of)s
		  AND is_cancelled = 0
		""",
		{"company": company, "accounts": tuple(accounts), "as_of": as_of},
	)
	return flt(row[0][0]) if row else 0.0


def _due_by_day(doctype, company, from_date, to_date):
	"""Outstanding amount due per day from submitted invoices, keyed by due_date."""
	rows = frappe.db.sql(
		f"""
		SELECT due_date, COALESCE(SUM(outstanding_amount), 0) AS amt
		FROM `tab{doctype}`
		WHERE company = %(company)s
		  AND docstatus = 1
		  AND outstanding_amount > 0
		  AND due_date BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY due_date
		""",
		{"company": company, "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)
	return {getdate(r.due_date): flt(r.amt) for r in rows if r.due_date}
