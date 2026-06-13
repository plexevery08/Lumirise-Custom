# Customer Quote Summary — parity with the web platform's customer dashboard
# (pending / approved / rejected / expired quotes per customer), extended with
# the quote-to-order link ERPNext makes possible.

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	conditions = {"docstatus": ("<", 2)}
	if filters.get("customer"):
		conditions["customer"] = filters["customer"]
	if filters.get("from_date"):
		conditions["transaction_date"] = (">=", filters["from_date"])

	sheets = frappe.get_all(
		"Price Sheet",
		filters=conditions,
		fields=["name", "customer", "customer_name", "status", "transaction_date", "quotation"],
	)

	by_customer = {}
	for sheet in sheets:
		row = by_customer.setdefault(sheet.customer, {
			"customer": sheet.customer,
			"customer_name": sheet.customer_name,
			"total_quotes": 0, "draft": 0, "pending": 0, "approved": 0,
			"rejected": 0, "expired": 0, "quotations": 0, "orders": 0,
			"last_quote_date": None,
		})
		row["total_quotes"] += 1
		key = (sheet.status or "Draft").lower().replace(" approval", "")
		if key in row:
			row[key] += 1
		if sheet.quotation:
			row["quotations"] += 1
			if frappe.db.exists(
				"Sales Order Item", {"prevdoc_docname": sheet.quotation, "docstatus": 1}
			):
				row["orders"] += 1
		if not row["last_quote_date"] or sheet.transaction_date > row["last_quote_date"]:
			row["last_quote_date"] = sheet.transaction_date

	data = sorted(by_customer.values(), key=lambda r: r["total_quotes"], reverse=True)

	columns = [
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link",
		 "options": "Customer", "width": 180},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "total_quotes", "label": _("Quotes"), "fieldtype": "Int", "width": 80},
		{"fieldname": "draft", "label": _("Draft"), "fieldtype": "Int", "width": 70},
		{"fieldname": "pending", "label": _("Pending"), "fieldtype": "Int", "width": 80},
		{"fieldname": "approved", "label": _("Approved"), "fieldtype": "Int", "width": 90},
		{"fieldname": "rejected", "label": _("Rejected"), "fieldtype": "Int", "width": 85},
		{"fieldname": "expired", "label": _("Expired"), "fieldtype": "Int", "width": 80},
		{"fieldname": "quotations", "label": _("Quotations"), "fieldtype": "Int", "width": 95},
		{"fieldname": "orders", "label": _("Converted to SO"), "fieldtype": "Int", "width": 110},
		{"fieldname": "last_quote_date", "label": _("Last Quote"), "fieldtype": "Date", "width": 100},
	]

	chart = None
	if data:
		top = data[:10]
		chart = {
			"data": {
				"labels": [r["customer_name"] or r["customer"] for r in top],
				"datasets": [
					{"name": _("Pending"), "values": [r["pending"] for r in top]},
					{"name": _("Approved"), "values": [r["approved"] for r in top]},
					{"name": _("Expired"), "values": [r["expired"] for r in top]},
				],
			},
			"type": "bar",
		}

	return columns, data, None, chart
