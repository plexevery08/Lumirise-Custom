"""Item / BOM costing — restored from the Pavan-era cloud implementation.

Spec: context/import/Lumirise-ERPNEXT/Implementation Details/Item_BOM_Costing.md
(ERP AIOS workspace). Field names are kept identical to the live-site custom
fields so the logic stays portable to the Frappe Cloud site.

Chain:
    Item landed cost (RMB -> INR + duty -> valuation_rate)
    -> Sub BOM rollup (custom_sub_bom_total)
    -> Parent BOM layered costing (custom_bom_cost)
    -> MOQ slab prices (custom_{1k,3k,6k,10k}_moq_price)
"""

import frappe
from frappe.utils import flt

# Layered percentage costs, applied in this exact order. Each tuple is
# (percent_fieldname, base_fieldname, value_fieldname, total_fieldname).
# Note: custom_interest_ keeps its trailing underscore for live-site parity.
COST_LAYERS = [
	("custom_dollar_rate_fluctuations", "custom_dollar_rate_fluctuations_base",
	 "custom_dollar_rate_fluctuations_value", "custom_dollar_rate_fluctuations_total"),
	("custom_interest_", "custom_interest_base",
	 "custom_interest_value", "custom_interest_total"),
	("custom_miscellaneous", "custom_miscellaneous_base",
	 "custom_miscellaneous_value", "custom_miscellaneous_total"),
	("custom_replacement", "custom_replacement_base",
	 "custom_replacement_value", "custom_replacement_total"),
	("custom_marketing_expenses", "custom_marketing_expenses_base",
	 "custom_marketing_expenses_value", "custom_marketing_expenses_total"),
]

MOQ_SLABS = ["1k", "3k", "6k", "10k"]

# Every BOM costing field derived by compute_bom_costing() — persisted with db_set
# (no re-validate) whenever a BOM is recomputed in place.
DERIVED_BOM_FIELDS = (
	["custom_raw_materials_total", "custom_sub_bom_total", "custom_bom_cost"]
	+ [f for layer in COST_LAYERS for f in layer[1:]]
	+ [f"custom_{slab}_moq_price" for slab in MOQ_SLABS]
)


# ---------------------------------------------------------------------------
# Item: landed cost
# ---------------------------------------------------------------------------

def item_validate(doc, method=None):
	"""Compute landed INR cost from RMB inputs and store it in valuation_rate."""
	rmb = flt(doc.get("custom_price_in_rmb"))
	rate = flt(doc.get("custom_rmb_to_inr_rate"))
	duty = flt(doc.get("custom_custom_duty"))

	if not (rmb and rate):
		return

	price_in_inr = flt(rmb * rate, 3)
	basic_duty = flt(price_in_inr * duty / 100.0, 3)
	doc.custom_price_in_inr = price_in_inr
	doc.custom_basic_custom_duty = basic_duty
	doc.valuation_rate = flt(price_in_inr + basic_duty, 3)


# ---------------------------------------------------------------------------
# BOM: row rates, rollup, layered costing, MOQ prices
# ---------------------------------------------------------------------------

def _row_rate(row):
	"""Rate resolution order: child BOM total -> item's active BOM total -> Item valuation_rate."""
	if row.bom_no:
		return flt(frappe.db.get_value("BOM", row.bom_no, "custom_sub_bom_total"))

	active_bom = frappe.db.get_value(
		"BOM", {"item": row.item_code, "is_active": 1, "docstatus": 1}, "name"
	)
	if active_bom:
		return flt(frappe.db.get_value("BOM", active_bom, "custom_sub_bom_total"))

	return flt(frappe.db.get_value("Item", row.item_code, "valuation_rate"))


def compute_bom_costing(doc):
	"""Pure computation: sets all costing fields on the BOM document in memory."""
	raw_total = 0.0
	for row in doc.get("items") or []:
		rate = _row_rate(row)
		row.rate = rate
		row.amount = flt(rate * flt(row.qty), 3)
		raw_total += row.amount

	doc.custom_raw_materials_total = flt(raw_total, 3)

	if doc.get("custom_bom_type") == "Sub BOM":
		# Intermediate assembly: material build-up + conversion only, no commercial layers.
		for pct_f, base_f, value_f, total_f in COST_LAYERS:
			doc.set(base_f, 0)
			doc.set(value_f, 0)
			doc.set(total_f, 0)
		sub_total = flt(raw_total + flt(doc.get("custom_conversion_cost")), 3)
		doc.custom_sub_bom_total = sub_total
		doc.custom_bom_cost = sub_total
		for slab in MOQ_SLABS:
			doc.set(f"custom_{slab}_moq_price", 0)
		return

	# Parent BOM: full layered costing.
	base = flt(
		raw_total
		+ flt(doc.get("custom_inward_transport_cost"))
		+ flt(doc.get("custom_factory_overheads")),
		3,
	)
	for pct_f, base_f, value_f, total_f in COST_LAYERS:
		pct = flt(doc.get(pct_f))
		value = flt(base * pct / 100.0, 3) if pct else 0.0
		doc.set(base_f, base)
		doc.set(value_f, value)
		doc.set(total_f, flt(base + value, 3))
		base = flt(base + value, 3)

	doc.custom_bom_cost = base
	doc.custom_sub_bom_total = base

	for slab in MOQ_SLABS:
		pct = flt(doc.get(f"custom_{slab}_moq_percentage"))
		doc.set(f"custom_{slab}_moq_price", flt(base * (1 + pct / 100.0), 3))


def bom_validate(doc, method=None):
	compute_bom_costing(doc)


def _persist_bom_costing(doc):
	"""Write the recomputed row rates/amounts + derived fields to the DB without
	re-running validation (used for in-place recompute of submitted BOMs)."""
	for row in doc.get("items") or []:
		row.db_set("rate", row.rate, update_modified=False)
		row.db_set("amount", row.amount, update_modified=False)
	for fieldname in DERIVED_BOM_FIELDS:
		doc.db_set(fieldname, doc.get(fieldname), update_modified=False)


def bom_on_update_after_submit(doc, method=None):
	"""Submitted BOMs keep manual inputs editable; recompute and persist the
	derived fields, then cascade to parent BOMs that consume this one."""
	compute_bom_costing(doc)
	_persist_bom_costing(doc)
	_cascade_to_parents(doc.name)


def _cascade_to_parents(bom_name, _seen=None):
	"""Recompute every submitted BOM that uses bom_name as a child row."""
	_seen = _seen or set()
	if bom_name in _seen:
		return
	_seen.add(bom_name)

	parents = frappe.get_all(
		"BOM Item",
		filters={"bom_no": bom_name, "parenttype": "BOM", "docstatus": 1},
		pluck="parent",
		distinct=True,
	)
	for parent in parents:
		parent_doc = frappe.get_doc("BOM", parent)
		compute_bom_costing(parent_doc)
		_persist_bom_costing(parent_doc)
		_cascade_to_parents(parent, _seen)


def get_bom_moq_price(item_code, moq):
	"""Base-price resolution for the Price Sheet: active Parent BOM MOQ slab price.

	Returns None when no costed Parent BOM exists (caller falls back to
	Lumirise Base Price).
	"""
	slab = {1000: "1k", 3000: "3k", 6000: "6k", 10000: "10k"}.get(int(moq))
	if not slab:
		return None

	bom = frappe.db.get_value(
		"BOM",
		{"item": item_code, "is_active": 1, "docstatus": 1, "custom_bom_type": "Parent BOM"},
		["name", f"custom_{slab}_moq_price", "custom_bom_cost"],
		as_dict=True,
	)
	if not bom:
		return None

	price = flt(bom.get(f"custom_{slab}_moq_price"))
	if price:
		return price
	# Fallback order from the spec: MOQ price -> custom_bom_cost.
	return flt(bom.custom_bom_cost) or None


# ---------------------------------------------------------------------------
# Auto-sync: keep BOM costs live after purchase / production / item-cost edits
# ---------------------------------------------------------------------------
# These streamline the (Supabase-derived) costing engine into the live flow so
# the BOM cost sheet refreshes automatically — replacing the manual Excel
# re-entry the client does today. All entrypoints are FAIL-SAFE: a costing
# refresh can never roll back a GRN / production / item save.

def recompute_boms_for_items(item_codes, _seen=None):
	"""Recompute every active, submitted BOM that DIRECTLY consumes any of the
	given items, then cascade up to the parent BOMs that consume those."""
	_seen = _seen if _seen is not None else set()
	item_codes = [c for c in set(item_codes or []) if c]
	if not item_codes:
		return
	boms = frappe.get_all(
		"BOM Item",
		filters={"item_code": ["in", item_codes], "parenttype": "BOM", "docstatus": 1},
		pluck="parent",
		distinct=True,
	)
	for bom in set(boms):
		if bom in _seen:
			continue
		_seen.add(bom)
		try:
			doc = frappe.get_doc("BOM", bom)
			compute_bom_costing(doc)
			_persist_bom_costing(doc)
			_cascade_to_parents(bom, _seen)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Costing auto-sync: recompute failed for BOM {bom}")


def item_on_update(doc, method=None):
	"""Item cost (valuation_rate) changed — e.g. an RMB price / FX / duty edit
	flowed through item_validate. Refresh every BOM that uses this item so the
	cost sheet stays current without re-saving each BOM by hand."""
	try:
		if doc.has_value_changed("valuation_rate"):
			recompute_boms_for_items([doc.name])
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Costing auto-sync: item_on_update failed")


def on_purchase_receipt(doc, method=None):
	"""GRN posted -> for DOMESTIC items (no RMB landed-cost model) adopt the
	actual receipt valuation as the item cost, then refresh dependent BOMs.
	RMB-import items keep their formula valuation but their BOMs still refresh."""
	try:
		affected = set()
		for row in doc.get("items") or []:
			item = row.get("item_code")
			if not item:
				continue
			affected.add(item)
			rmb = frappe.db.get_value("Item", item, "custom_price_in_rmb")
			if not flt(rmb) and flt(row.get("valuation_rate")):
				frappe.db.set_value(
					"Item", item, "valuation_rate",
					flt(row.get("valuation_rate"), 3), update_modified=False,
				)
		recompute_boms_for_items(affected)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Costing auto-sync: on_purchase_receipt failed")


def on_stock_entry(doc, method=None):
	"""Production posted (Manufacture stock entry) -> refresh the BOMs for the
	produced FG and consumed components so finished-goods cost stays current."""
	try:
		purpose = doc.get("purpose") or doc.get("stock_entry_type")
		if purpose != "Manufacture":
			return
		items = {r.get("item_code") for r in (doc.get("items") or []) if r.get("item_code")}
		recompute_boms_for_items(items)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Costing auto-sync: on_stock_entry failed")
