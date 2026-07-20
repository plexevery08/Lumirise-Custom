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

import re

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from lumirise_custom import defaults as config

# Purchase hands in a sheet a human filled in Excel. Accept every header spelling we
# have actually seen rather than demanding a byte-perfect file: our own template
# (item_code), Frappe's Data Import export (Item Code (Prices)), and the field labels
# (Rate (INR) (Prices)). Everything normalises to the fieldname on the right.
_HEADER_ALIASES = {
	"item": "item_code",
	"itemcode": "item_code",
	"item_code": "item_code",
	"item_name": "item_name",
	"uom": "uom",
	"unit": "uom",
	"supplier": "supplier",
	"vendor": "supplier",
	"min": "min_qty",
	"min_qty": "min_qty",
	"max": "max_qty",
	"max_qty": "max_qty",
	"currency": "currency",
	"exchange_rate": "conversion_rate",
	"conversion_rate": "conversion_rate",
	"price": "rate",
	"rate": "rate",
	"preferred": "preferred",
}


def _norm_header(h):
	"""'Rate (INR) (Prices)' -> 'rate';  'item_code (Prices)' -> 'item_code'."""
	h = str(h or "").strip().lower()
	while re.search(r"\s*\([^)]*\)\s*$", h):  # peel trailing "(Prices)", "(INR)" …
		h = re.sub(r"\s*\([^)]*\)\s*$", "", h)
	h = re.sub(r"[^a-z0-9]+", "_", h).strip("_")
	return _HEADER_ALIASES.get(h, h)


class RMPriceBook(Document):
	def validate(self):
		"""Resolve each row into company currency before anything reaches costing.

		Vendors quote in their own currency (the China housing vendors quote CNY).
		`rate` is what they quoted; `base_rate` is what costing consumes. Never let a
		foreign-currency rate through unconverted -- that silently understates every
		BOM that uses the item.
		"""
		if not self.company:
			self.company = config.get_company()
		company_currency = frappe.get_cached_value("Company", self.company, "default_currency")

		for row in self.items:
			if not row.currency:
				row.currency = company_currency

			if row.currency == company_currency:
				row.conversion_rate = 1
			elif not flt(row.conversion_rate):
				from erpnext.setup.utils import get_exchange_rate

				row.conversion_rate = flt(
					get_exchange_rate(row.currency, company_currency, self.effective_from)
				)

			if flt(row.conversion_rate) <= 0:
				frappe.throw(
					f"Row {row.idx} ({row.item_code}): no exchange rate found for "
					f"{row.currency} -> {company_currency} on {self.effective_from}. "
					f"Enter the Exchange Rate manually or add a Currency Exchange record."
				)

			row.base_rate = flt(row.rate) * flt(row.conversion_rate)

	def before_submit(self):
		"""Rows are mandatory to APPROVE, not to save.

		`items` is deliberately NOT reqd on the doctype: 'Import Rows from File' needs a
		saved docname to import into, so a reqd table made the upload button unusable --
		you could not save without rows, and could not import rows without saving.
		Draft may be empty; nothing reaches costing until submit, which is gated here.
		"""
		if not self.items:
			frappe.throw(
				"Add at least one price row before approving — "
				"attach the price file and click 'Import Rows from File'."
			)

	def on_submit(self):
		"""MD-approved -> push rates into costing and refresh dependent BOMs."""
		touched = []
		for row in self.items:
			if not row.item_code or flt(row.base_rate) <= 0:
				continue
			# db.set_value (not a full save) so Item.validate's import-costing model
			# does not overwrite the manual book rate for domestic items.
			# base_rate (company currency), never the raw vendor-currency rate.
			frappe.db.set_value(
				"Item", row.item_code, "valuation_rate", flt(row.base_rate), update_modified=False
			)
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
		return [], []
	header = [_norm_header(c) for c in rows[0]]
	out = []
	for r in rows[1:]:
		out.append({header[i]: r[i] for i in range(len(header)) if i < len(r)})
	return out, [str(c or "").strip() for c in rows[0]]


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

	data, raw_headers = _read_price_file(file_url)
	if not data:
		frappe.throw(
			f"No data rows found in <b>{file_url}</b> — the file has a header row but nothing under it."
		)

	# Fail loudly on an unrecognised sheet. Silently importing 0 rows and leaving the
	# user to guess is the bug this replaces.
	if not any((d.get("item_code") or "") for d in data):
		frappe.throw(
			"No <b>item_code</b> column found in the uploaded file.<br><br>"
			f"Headers found: <b>{', '.join(raw_headers) or '(none)'}</b><br>"
			"Expected a column named <b>item_code</b> (or 'Item Code', 'Item Code (Prices)').<br><br>"
			"Click <b>Download Template</b> for the exact format."
		)

	doc.set("items", [])
	added = 0
	skipped, no_rate = [], []
	for d in data:
		code = str(d.get("item_code") or "").strip()
		rate = flt(d.get("rate") or 0)
		if not code:
			continue
		if not frappe.db.exists("Item", code):
			skipped.append(code)
			continue
		if rate <= 0:
			no_rate.append(code)
			continue
		# v2 columns (all optional): supplier / min_qty / max_qty / preferred.
		sup = (d.get("supplier") or "").strip()
		if sup and not frappe.db.exists("Supplier", sup):
			sup = None  # unknown supplier — leave blank rather than fail the whole import
		doc.append("items", {
			"item_code": code,
			"rate": rate,
			"uom": (d.get("uom") or config.item_uom(code)),
			"supplier": sup or None,
			# Blank currency/conversion_rate are resolved against company currency in validate().
			"currency": str(d.get("currency") or "").strip().upper() or None,
			"conversion_rate": flt(d.get("conversion_rate") or 0),
			"min_qty": flt(d.get("min_qty") or 0),
			"max_qty": flt(d.get("max_qty") or 0),
			"preferred": 1 if str(d.get("preferred") or "").strip().lower() in ("1", "yes", "y", "true") else 0,
		})
		added += 1
	doc.save()

	msg = f"Imported <b>{added}</b> price row(s) from {len(data)} file row(s)."

	# A sheet with no currency column silently lands every rate in company currency.
	# For the China vendors that would book a CNY number as INR and understate every
	# BOM -- so say it out loud rather than let it pass as a clean import.
	if added and not any(str(d.get("currency") or "").strip() for d in data):
		company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
		msg += (
			f"<br><br><b>No currency column in this file</b> — all {added} row(s) were treated as "
			f"<b>{company_currency}</b>. If these are vendor-currency rates (e.g. CNY), add a "
			f"<b>currency</b> column and re-import, or costing will book them as {company_currency}."
		)
	if skipped:
		msg += (
			f"<br><br>Skipped <b>{len(skipped)}</b> row(s) — item does not exist on this site: "
			f"{', '.join(skipped[:10])}{' …' if len(skipped) > 10 else ''}"
		)
	if no_rate:
		msg += (
			f"<br><br>Skipped <b>{len(no_rate)}</b> row(s) — rate is blank or zero: "
			f"{', '.join(no_rate[:10])}{' …' if len(no_rate) > 10 else ''}"
		)
	frappe.msgprint(msg, title="Price Import", indicator="green" if added else "red")
	return added


@frappe.whitelist()
def get_rm_price_template():
	"""CSV template (header row) for the RM Price Book v2 upload — item, vendor,
	qty-range, currency, rate, preferred. Purchase downloads this, fills it, re-uploads.

	currency/conversion_rate are optional: blank currency = company currency, and a
	blank conversion_rate is auto-fetched from Currency Exchange for foreign rows.
	"""
	return (
		"item_code,item_name,uom,supplier,min_qty,max_qty,"
		"currency,conversion_rate,rate,preferred\n"
	)
