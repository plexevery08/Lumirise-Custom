"""One-off migration: Sales Platform Supabase CSV export -> ERPNext (plan Phase E).

Source: CSV dumps in `context/import/Supabase Import/` (Supabase project is
gone; these are the dashboard exports, 2026-06-10).

    product_pricing      -> Lumirise Base Price (+ Items + Item Groups)
    mono_box_pricing     -> Mono Box Pricing (+ Box Finish)
    master_box_pricing   -> Master Box Pricing
    transport_pricing    -> Transport Pricing
    price_sheet_history  -> Price Sheet (submitted, rows copied verbatim from
                            the stored price_sheet_data JSON — NOT regenerated,
                            so historical numbers stay exactly as quoted)
    profiles             -> used only to resolve approved_by UUIDs in comments

Notes:
- The export has no quotation_code column and no counters table, so sheets
  are named on the LQ-MMYY-#### series chronologically per month, and the
  tabSeries counters are set so new sheets continue cleanly.
- Sheets with no customer_name land on the placeholder customer below.
- audit_log is intentionally not imported (Version history replaces it);
  the CSV stays in context/import/ as the archive.

Run:
    bench --site site.com execute lumirise_custom.demo.import_sales_platform.run

Idempotent: skips masters that already exist, wipes previously imported
Price Sheets (those carrying a supabase_id comment marker) before reimport.
"""

import csv
import json
import sys
from datetime import timedelta

import frappe
from frappe.utils import add_days, flt, getdate

CSV_DIR = ("/home/riddhi/Documents/ERP AIOS Lumirise/context/import/"
	"Supabase Import")
HSN_CODE = "85391000"  # placeholder HSN on the local bench; revisit before live
HISTORY_GROUP = "SALES PLATFORM"
PLACEHOLDER_CUSTOMER = "UNSPECIFIED (SALES PLATFORM)"
MARKER = "supabase_price_sheet_id:"

csv.field_size_limit(sys.maxsize)

stats = {}


def read(table):
	with open(f"{CSV_DIR}/{table}_rows.csv") as f:
		return list(csv.DictReader(f))


def log(label, n):
	stats[label] = n
	print(f"  {label}: {n}")


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------

def ensure_item_group(name):
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc({
			"doctype": "Item Group", "item_group_name": name,
			"parent_item_group": "All Item Groups",
		}).insert(ignore_permissions=True)


def ensure_item(name, group):
	if frappe.db.exists("Item", name):
		return
	frappe.get_doc({
		"doctype": "Item", "item_code": name, "item_name": name,
		"item_group": group, "stock_uom": "Nos", "gst_hsn_code": HSN_CODE,
	}).insert(ignore_permissions=True)


def import_items():
	"""Items + Item Groups from every master table, plus models that only
	appear inside historical price sheets."""
	item_category = {}
	for table in ("product_pricing", "mono_box_pricing", "master_box_pricing",
			"transport_pricing"):
		for row in read(table):
			item_category.setdefault(row["product_name"].strip(),
				row["category"].strip() or HISTORY_GROUP)

	for sheet in read("price_sheet_history"):
		data = json.loads(sheet["price_sheet_data"] or "{}")
		for product_sheet in data.get("productSheets", []):
			for row in product_sheet.get("rows", []):
				model = (row.get("model") or "").strip()
				if model:
					item_category.setdefault(model, HISTORY_GROUP)

	for group in sorted({g for g in item_category.values()} | {HISTORY_GROUP}):
		ensure_item_group(group)
	created = 0
	for name, group in item_category.items():
		if not frappe.db.exists("Item", name):
			ensure_item(name, group)
			created += 1
	log("items created", created)
	log("items total referenced", len(item_category))
	return item_category


def import_box_finishes():
	finishes = {r["box_finish"].strip() for r in read("mono_box_pricing")}
	finishes |= {r["box_finish"].strip() for r in read("master_box_pricing")}
	created = 0
	for finish in sorted(f for f in finishes if f):
		if not frappe.db.exists("Box Finish", finish):
			frappe.get_doc({"doctype": "Box Finish", "finish_name": finish}).insert(
				ignore_permissions=True)
			created += 1
	log("box finishes created", created)


def import_master(table, doctype, mapper, unique_filters):
	created = skipped = 0
	for row in read(table):
		doc_fields = mapper(row)
		if frappe.db.exists(doctype, unique_filters(doc_fields)):
			skipped += 1
			continue
		frappe.get_doc(dict(doc_fields, doctype=doctype)).insert(
			ignore_permissions=True)
		created += 1
	log(f"{doctype} created", created)
	if skipped:
		log(f"{doctype} skipped (already present)", skipped)


def import_pricing_masters():
	import_master(
		"product_pricing", "Lumirise Base Price",
		lambda r: {
			"item": r["product_name"].strip(), "category": r["category"].strip(),
			"moq": r["moq"], "price": flt(r["price"]),
		},
		lambda d: {"item": d["item"], "moq": d["moq"]},
	)
	import_master(
		"mono_box_pricing", "Mono Box Pricing",
		lambda r: {
			"item": r["product_name"].strip(), "category": r["category"].strip(),
			"box_finish": r["box_finish"].strip(), "moq": r["moq"],
			"purchase_price": flt(r["purchase_price"]),
			"selling_price": flt(r["selling_price"]),
			"profit_price": flt(r["profit_price"]),
		},
		lambda d: {"item": d["item"], "box_finish": d["box_finish"], "moq": d["moq"]},
	)
	import_master(
		"master_box_pricing", "Master Box Pricing",
		lambda r: {
			"item": r["product_name"].strip(), "category": r["category"].strip(),
			"box_finish": r["box_finish"].strip(), "caselot": int(flt(r["caselot"])),
			"purchase_price": flt(r["purchase_price"]),
			"price_per_unit": flt(r["price_per_unit"]),
		},
		lambda d: {"item": d["item"], "box_finish": d["box_finish"],
			"caselot": d["caselot"]},
	)
	import_master(
		"transport_pricing", "Transport Pricing",
		lambda r: {
			"item": r["product_name"].strip(), "category": r["category"].strip(),
			"transport_type": r["transport_type"].strip(),
			"transport_zone": r["transport_zone"].strip(),
			"cost_per_unit": flt(r["cost_per_unit"]),
		},
		lambda d: {"item": d["item"], "transport_type": d["transport_type"],
			"transport_zone": d["transport_zone"]},
	)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def import_customers():
	names = {r["customer_name"].strip() for r in read("price_sheet_history")}
	names = {n for n in names if n} | {PLACEHOLDER_CUSTOMER}
	created = 0
	for name in sorted(names):
		if not frappe.db.exists("Customer", {"customer_name": name}):
			frappe.get_doc({
				"doctype": "Customer", "customer_name": name,
				"customer_group": "Commercial", "territory": "India",
			}).insert(ignore_permissions=True)
			created += 1
	log("customers created", created)


# ---------------------------------------------------------------------------
# Historical price sheets
# ---------------------------------------------------------------------------

def wipe_previous_import():
	"""Delete Price Sheets created by an earlier run of this script."""
	marked = frappe.get_all("Comment", filters={
		"reference_doctype": "Price Sheet",
		"content": ("like", f"%{MARKER}%"),
	}, pluck="reference_name")
	for name in set(marked):
		if frappe.db.exists("Price Sheet", name):
			frappe.db.set_value("Price Sheet", name, "docstatus", 2)
			frappe.delete_doc("Price Sheet", name, force=True)
	if marked:
		log("previously imported sheets wiped", len(set(marked)))


def sheet_rows_from_json(data):
	"""Flatten the platform's stored productSheets rows into Price Sheet Row
	dicts — numbers copied verbatim, one row per finish + a baseline row."""
	rows = []
	for product_sheet in data.get("productSheets", []):
		for row in product_sheet.get("rows", []):
			model = (row.get("model") or "").strip()
			if not model:
				continue
			common = {
				"item": model,
				"moq": row.get("moq"),
				"moq_label": row.get("moqLabel"),
				"caselot": row.get("masterCaselot"),
				"base_price": flt(row.get("baseLightPrice")),
				"price_source": "Imported",
				"master_box_finish": row.get("masterBoxFinish"),
				"master_box_cost_per_light": row.get("masterBoxCostPerLight"),
				"transport_cost": flt(row.get("transportCostPerLight")),
				"credit_percentage": flt(row.get("creditPercentage")),
				"baseline_total": row.get("finalBaselineTotal"),
				"total_without_mono_box": row.get("finalBaselineTotal"),
			}
			rows.append(dict(common,
				box_finish="No Mono Box",
				mono_profit_price=None,
				total=row.get("finalBaselineTotal"),
				final_total=row.get("finalBaselineTotal"),
			))
			for mono in row.get("monoBoxDetails") or []:
				rows.append(dict(common,
					box_finish=mono.get("finish"),
					mono_purchase_price=mono.get("purchasePrice"),
					mono_selling_price=mono.get("sellingPrice"),
					mono_profit_price=mono.get("profit"),
					total=mono.get("variant1"),
					final_total=mono.get("variant1"),
				))
	return rows


def import_price_sheets():
	profiles = {p["user_id"]: p["full_name"] for p in read("profiles")}
	history = sorted(read("price_sheet_history"), key=lambda r: r["generated_at"])

	month_counters = {}
	imported = skipped = 0
	for record in history:
		data = json.loads(record["price_sheet_data"] or "{}")
		rows = sheet_rows_from_json(data)
		if not rows:
			skipped += 1
			continue

		generated = getdate(record["generated_at"][:10])
		prefix = f"LQ-{generated.strftime('%m%y')}-"
		month_counters[prefix] = month_counters.get(prefix, 0) + 1
		name = f"{prefix}{month_counters[prefix]:04d}"

		configs = json.loads(record["product_configs"] or "[]") or [{}]
		cfg = configs[0]
		customer_name = record["customer_name"].strip() or PLACEHOLDER_CUSTOMER
		customer = frappe.db.get_value("Customer", {"customer_name": customer_name})

		doc = frappe.new_doc("Price Sheet")
		doc.customer = customer
		doc.transaction_date = generated
		doc.valid_till = add_days(generated, 7)
		doc.delivery_type = ("Transport" if cfg.get("deliveryType") == "Transport"
			else "Ex-Factory")
		doc.transport_type = cfg.get("transportType")
		doc.transport_zone = cfg.get("transportZone")
		doc.payment_type = ("Credit" if cfg.get("paymentType") == "Credit"
			else "Advance")
		doc.credit_days = int(flt(cfg.get("creditDays")))
		doc.master_box_finish = (cfg.get("masterBoxFinish")
			if cfg.get("masterBoxFinish") and frappe.db.exists(
				"Box Finish", cfg.get("masterBoxFinish")) else None)
		doc.master_box_caselots = ",".join(
			str(c) for c in cfg.get("masterBoxCaselots") or []) or None

		for item in sorted({r["item"] for r in rows}):
			doc.append("products", {"item": item})
		for finish in cfg.get("allMonoBoxTypes") or []:
			if finish not in ("No Box", "No Mono Box") and frappe.db.exists(
					"Box Finish", finish):
				doc.append("mono_box_finishes", {"box_finish": finish})
		for row in rows:
			doc.append("rows", row)

		approved = record["approval_status"] == "approved"
		doc.status = "Approved" if approved else "Expired"
		doc.docstatus = 1
		doc.flags.ignore_validate = True
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, set_name=name)

		if approved and record["approved_at"]:
			doc.db_set("approved_at", record["approved_at"][:19],
				update_modified=False)

		approver = profiles.get(record["approved_by"], record["approved_by"])
		doc.add_comment("Comment",
			f"{MARKER}{record['id']} | platform status: {record['approval_status']}"
			+ (f" | approved by: {approver}" if approved else ""))
		imported += 1

	log("price sheets imported", imported)
	if skipped:
		log("price sheets skipped (no rows in JSON)", skipped)

	# Continue the LQ- series after the imported names.
	for prefix, current in month_counters.items():
		frappe.db.sql(
			"""insert into tabSeries (name, current) values (%s, %s)
			on duplicate key update current = greatest(current, %s)""",
			(prefix, current, current),
		)
	log("series counters set", len(month_counters))


def run():
	wipe_previous_import()
	print("Masters:")
	import_items()
	import_box_finishes()
	import_pricing_masters()
	import_customers()
	print("Price sheets:")
	import_price_sheets()
	frappe.db.commit()
	print("\nDone.", json.dumps(stats, indent=1))
	return stats
