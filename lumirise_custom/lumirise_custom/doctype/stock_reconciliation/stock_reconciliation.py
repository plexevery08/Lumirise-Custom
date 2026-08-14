"""Helpers for the Stock Reconciliation physical-count workflow."""

import csv
import io

import frappe


@frappe.whitelist()
def get_stock_reconciliation_template():
	"""Return the blank CSV used for a warehouse physical stock count.

	The headers use fieldname-style names, matching the RM Price Book template and
	ERPNext's import conventions. ``qty`` is the physically counted quantity; the
	location columns let Stores record the exact bay/rack/bin during the count.
	"""
	columns = ["item_code", "item_name", "qty", "warehouse", "bay", "rack", "bin"]
	stream = io.StringIO(newline="")
	csv.writer(stream, lineterminator="\n").writerow(columns)
	return stream.getvalue()
