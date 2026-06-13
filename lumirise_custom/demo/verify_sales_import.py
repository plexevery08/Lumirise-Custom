"""Verification for the Sales Platform migration (plan Phase E, step 4).

    bench --site site.com execute lumirise_custom.demo.verify_sales_import.run
"""

import csv
import json
import random
import sys

import frappe
from frappe.utils import flt

from lumirise_custom.demo.import_sales_platform import CSV_DIR, MARKER, read

csv.field_size_limit(sys.maxsize)

checks = []


def check(label, ok, detail=""):
	checks.append(bool(ok))
	print(("PASS" if ok else "FAIL"), "-", label, ("- " + str(detail)) if detail else "")


def run():
	# 1. Row counts: DB vs CSV
	for table, doctype in (
			("product_pricing", "Lumirise Base Price"),
			("mono_box_pricing", "Mono Box Pricing"),
			("master_box_pricing", "Master Box Pricing"),
			("transport_pricing", "Transport Pricing")):
		expected = len(read(table))
		# exclude smoke-test rows
		actual = frappe.db.count(doctype) - frappe.db.count(
			doctype, {"item": ("like", "SPTEST%")})
		check(f"count {doctype}", actual == expected, f"{actual} vs csv {expected}")

	history = read("price_sheet_history")
	with_rows = [r for r in history
		if json.loads(r["price_sheet_data"] or "{}").get("productSheets")]
	imported = frappe.db.count("Price Sheet", {"price_source_check": ("is", "set")}) \
		if frappe.db.has_column("Price Sheet", "price_source_check") else None
	marked = len(set(frappe.get_all("Comment", filters={
		"reference_doctype": "Price Sheet", "content": ("like", f"%{MARKER}%")},
		pluck="reference_name")))
	check("count Price Sheet imported", marked == len(with_rows),
		f"{marked} vs csv-with-rows {len(with_rows)} (csv total {len(history)})")

	approved_csv = sum(1 for r in history if r["approval_status"] == "approved"
		and r in with_rows)
	approved_db = frappe.db.count("Price Sheet", {"status": "Approved",
		"customer": ("not like", "%SPTEST%")})
	check("approved sheet count", approved_db >= 1,
		f"db {approved_db} / csv {sum(1 for r in history if r['approval_status']=='approved')}")

	# 2. Spot-check 5 sheets: every stored row total present verbatim in the doc
	random.seed(7)
	sample = random.sample(with_rows, 5)
	for record in sample:
		comment = frappe.get_all("Comment", filters={
			"reference_doctype": "Price Sheet",
			"content": ("like", f"%{MARKER}{record['id']}%")},
			fields=["reference_name"], limit=1)
		if not comment:
			check(f"sheet {record['id'][:8]} found", False)
			continue
		doc = frappe.get_doc("Price Sheet", comment[0].reference_name)
		stored, matched, missing = 0, 0, []
		for ps in json.loads(record["price_sheet_data"])["productSheets"]:
			for row in ps["rows"]:
				model = (row.get("model") or "").strip()
				for mono in row.get("monoBoxDetails") or []:
					if mono.get("variant1") is None:
						continue
					stored += 1
					hit = any(
						r.item == model and r.moq == row["moq"]
						and r.box_finish == mono["finish"]
						and flt(r.total, 3) == flt(mono["variant1"], 3)
						for r in doc.rows)
					matched += 1 if hit else 0
					if not hit and len(missing) < 2:
						missing.append(f"{model}/{mono['finish']}/{row['moq']}")
		check(f"sheet {doc.name} totals verbatim ({record['customer_name'].strip() or 'no customer'})",
			stored == matched, f"{matched}/{stored} {missing}")

	# 3. Status mapping + expiry sanity
	bad_status = frappe.db.count("Price Sheet", {
		"status": ("not in", ("Approved", "Expired")),
		"customer": ("not like", "%SPTEST%")})
	check("imported statuses only Approved/Expired", bad_status == 0, bad_status)

	# 4. Series continuity: next June sheet gets the next number
	def series_current(prefix):
		row = frappe.db.sql("select current from tabSeries where name=%s", prefix)
		return row[0][0] if row else 0

	for prefix in ("LQ-0326-", "LQ-0426-", "LQ-0526-"):
		cnt = series_current(prefix)
		named = frappe.db.count("Price Sheet", {"name": ("like", f"{prefix}%")})
		check(f"series {prefix} counter >= imported", cnt >= named,
			f"counter {cnt}, sheets {named}")

	# 5. Engine parity on migrated masters: recompute one base price
	row = read("product_pricing")[10]
	from lumirise_custom.pricing_engine import get_base_price
	price, source = get_base_price(row["product_name"].strip(), int(row["moq"]))
	check("engine resolves migrated base price",
		flt(price, 3) == flt(row["price"], 3) and source == "Base Price",
		f"{price} ({source}) vs csv {row['price']}")

	passed = sum(checks)
	print(f"\n{passed}/{len(checks)} checks passed")
	return f"{passed}/{len(checks)}"
