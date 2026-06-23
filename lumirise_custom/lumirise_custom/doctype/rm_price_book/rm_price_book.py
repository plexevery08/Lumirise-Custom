"""RM Price Book -- the monthly raw-material purchase prices, MD-approved.

Ajay review 2026-06-14 (00:59:35-01:02:56): "price book should be updated by
purchase people... every month... and it should be approved by MD. Once the price
book is updated, you people can fetch the data from price book." Manual entry is
unmanageable -- "one item will be having at least 29 pricings" -- so prices come in
via a CSV/Excel upload.

Flow: Purchase fills/uploads the book (Draft) -> Submit for MD Approval -> MD
Approve (workflow in approval_setup.py). On approval (submit) the approved rates are
pushed to Item.valuation_rate and every dependent BOM cost is recomputed, so all
costing immediately uses the current month's prices.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class RMPriceBook(Document):
	def on_submit(self):
		"""MD-approved -> push rates into costing and refresh dependent BOMs."""
		touched = []
		for row in self.items:
			if not row.item_code or flt(row.rate) <= 0:
				continue
			# db.set_value (not a full save) so Item.validate's import-costing model
			# does not overwrite the manual book rate for domestic items.
			frappe.db.set_value("Item", row.item_code, "valuation_rate", flt(row.rate), update_modified=False)
			touched.append(row.item_code)
		if touched:
			try:
				from lumirise_custom.costing import recompute_boms_for_items
				recompute_boms_for_items(touched)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "RM Price Book: BOM recompute failed")
		frappe.msgprint(
			f"Approved — pushed {len(touched)} raw-material price(s) into costing.",
			indicator="green", alert=True)


def _read_price_file(file_url):
	"""Return a list of header-keyed dicts from an attached CSV or XLSX."""
	from frappe.utils.file_manager import get_file

	fname, content = get_file(file_url)
	lower = (fname or "").lower()
	if lower.endswith((".xlsx", ".xls")):
		from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file
		rows = read_xlsx_file_from_attached_file(file_url=file_url)
	else:
		from frappe.utils.csvutils import read_csv_content
		rows = read_csv_content(content)
	rows = [r for r in (rows or []) if any((c not in (None, "")) for c in r)]
	if not rows:
		return []
	header = [str(c or "").strip().lower() for c in rows[0]]
	out = []
	for r in rows[1:]:
		out.append({header[i]: r[i] for i in range(len(header)) if i < len(r)})
	return out


@frappe.whitelist()
def import_rows(price_book, file_url=None):
	"""Parse the attached CSV/Excel into the price rows. Columns (header row):
	item_code, rate [, uom]. Replaces the existing rows. Returns the row count."""
	doc = frappe.get_doc("RM Price Book", price_book)
	if doc.docstatus != 0:
		frappe.throw("Price file can only be imported while the book is in Draft.")
	file_url = file_url or doc.upload_file
	if not file_url:
		frappe.throw("Attach a price file (CSV/Excel) first.")

	data = _read_price_file(file_url)
	if not data:
		frappe.throw("No rows found in the uploaded file.")

	doc.set("items", [])
	added = 0
	skipped = []
	for d in data:
		code = (d.get("item_code") or d.get("item") or "").strip()
		rate = flt(d.get("rate") or d.get("price") or 0)
		if not code:
			continue
		if not frappe.db.exists("Item", code):
			skipped.append(code)
			continue
		doc.append("items", {"item_code": code, "rate": rate, "uom": (d.get("uom") or "Nos")})
		added += 1
	doc.save()
	msg = f"Imported {added} price row(s)."
	if skipped:
		msg += f" Skipped unknown item(s): {', '.join(skipped[:10])}"
	frappe.msgprint(msg, indicator="blue")
	return added
