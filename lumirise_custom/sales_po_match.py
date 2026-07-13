"""PO-to-SO match check (WP-1.4, v1).

Focus 9 lets a coordinator hand-type a Sales Order with no validation against the
customer's PO — off-PO items/qty/rates slip through. There is no structured customer-PO
document to line-match against yet (that is v2, a client decision), so v1 annotates the
Sales Order with what IS checkable today, keyed off the dedicated `lr_customer_po`
field (NOT the standard `po_no`, which ERPNext also uses for the internal-transfer /
inter-company flow):

  1. customer PO number present in `lr_customer_po`;
  2. that PO number not already used on another SO for the same customer (Lumirise's
     "one customer PO = one SO" rule) — a soft note, since we no longer rely on the
     native po_no duplicate guard (the customer PO now lives in a custom field); and
  3. per-line qty/rate sanity against the SOURCE Quotation (SO Item.prevdoc_docname),
     within a configurable rate tolerance; silently skipped for a direct SO with no quote.

Fail-safe: anything unexpected is logged and never blocks the Sales Order.
"""

import frappe
from frappe.utils import flt


def validate_po_match(doc, method=None):
	try:
		notes = []
		po = (doc.get("lr_customer_po") or "").strip()
		if not po:
			notes.append("Customer Purchase Order number is blank.")
		else:
			dupes = frappe.get_all(
				"Sales Order",
				filters={
					"lr_customer_po": po,
					"customer": doc.customer,
					"name": ["!=", doc.name or "new"],
					"docstatus": ["<", 2],
				},
				pluck="name",
			)
			if dupes:
				notes.append(f"Customer PO {po} already used on: {', '.join(dupes[:5])}.")
		notes.extend(_sanity_vs_quotation(doc))
		doc.lr_po_match_status = "Exception" if notes else "Matched"
		doc.lr_po_match_note = (" ".join(notes))[:500]
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Lumirise PO-match validator failed")


def _sanity_vs_quotation(doc):
	"""Compare each SO line to its source Quotation line (by item_code). Lines not
	sourced from a Quotation (direct SO) carry no prevdoc_docname and are skipped."""
	notes = []
	tol = flt(frappe.db.get_single_value("Lumirise Operations Settings", "po_rate_tolerance_pct")) or 5.0
	for it in doc.items:
		quote = it.get("prevdoc_docname")
		if not quote:
			continue
		q = frappe.db.get_value(
			"Quotation Item",
			{"parent": quote, "item_code": it.item_code},
			["rate", "qty"],
			as_dict=True,
		)
		if not q:
			continue
		if flt(q.rate) and abs(flt(it.rate) - flt(q.rate)) > flt(q.rate) * tol / 100.0:
			notes.append(f"Row {it.idx} {it.item_code}: rate {flt(it.rate):g} vs quote {flt(q.rate):g} (>{tol:g}%).")
		if flt(it.qty) > flt(q.qty):
			notes.append(f"Row {it.idx} {it.item_code}: qty {flt(it.qty):g} > quoted {flt(q.qty):g}.")
	return notes
