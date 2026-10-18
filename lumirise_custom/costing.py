"""Authoritative commercial-costing engine for Items, BOMs, and quotations.

Cost-source precedence:
    approved RM Price Book -> landed import formula -> last purchase cost
    -> ERPNext Item valuation rate

Every custom BOM total is a *per finished unit* value. BOM Item amounts remain
batch amounts, then the raw-material batch total is divided by ``BOM.quantity``
before conversion costs, overheads, compound layers, and MOQ margins are added.
"""

import frappe
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from lumirise_custom.costing_math import (
	calculate_bom_cost,
	calculate_import_cost,
	effective_exchange_rate,
	round_cost,
	select_price_book_row,
)

COST_LAYERS = [
	(
		"custom_dollar_rate_fluctuations",
		"custom_dollar_rate_fluctuations_base",
		"custom_dollar_rate_fluctuations_value",
		"custom_dollar_rate_fluctuations_total",
	),
	("custom_interest_", "custom_interest_base", "custom_interest_value", "custom_interest_total"),
	(
		"custom_miscellaneous",
		"custom_miscellaneous_base",
		"custom_miscellaneous_value",
		"custom_miscellaneous_total",
	),
	(
		"custom_replacement",
		"custom_replacement_base",
		"custom_replacement_value",
		"custom_replacement_total",
	),
	(
		"custom_marketing_expenses",
		"custom_marketing_expenses_base",
		"custom_marketing_expenses_value",
		"custom_marketing_expenses_total",
	),
]

MOQ_SLABS = ("1k", "3k", "6k", "10k")
DEFAULT_MOQ_PERCENTAGES = {"1k": 12.0, "3k": 10.0, "6k": 8.0, "10k": 6.0}
COSTING_PRECISION = 3

DERIVED_BOM_FIELDS = (
	[
		"custom_raw_materials_batch_total",
		"custom_raw_materials_total",
		"custom_sub_bom_total",
		"custom_bom_cost",
		"custom_costing_status",
		"custom_missing_cost_items",
	]
	+ [fieldname for layer in COST_LAYERS for fieldname in layer[1:]]
	+ [f"custom_{slab}_moq_price" for slab in MOQ_SLABS]
)

ITEM_COST_FIELDS = (
	"custom_costing_rate",
	"custom_costing_rate_source",
	"custom_costing_rate_reference",
	"custom_costing_rate_updated_on",
)

SOURCE_PRICE_BOOK = "Approved RM Price Book"
SOURCE_IMPORT = "Landed Import Formula"
SOURCE_PURCHASE = "Last Purchase Receipt"
SOURCE_VALUATION = "ERP Valuation Fallback"
SOURCE_MISSING = "Missing Cost"


def get_costing_settings():
	"""Read costing controls with safe defaults for pre-migration sites."""
	try:
		settings = frappe.get_cached_doc("Sales Platform Settings")
	except Exception:
		settings = frappe._dict()
	use_global_rate = settings.get("use_global_rmb_to_inr_rate")
	return frappe._dict(
		precision=COSTING_PRECISION,
		default_rmb_to_inr_rate=flt(settings.get("default_rmb_to_inr_rate")),
		use_global_rmb_to_inr_rate=(1 if use_global_rate in (None, "") else cint(use_global_rate)),
		sync_costing_rate_to_valuation_rate=cint(settings.get("sync_costing_rate_to_valuation_rate")),
		default_moq_percentages={
			slab: (
				DEFAULT_MOQ_PERCENTAGES[slab]
				if settings.get(f"default_{slab}_moq_percentage") in (None, "")
				else flt(settings.get(f"default_{slab}_moq_percentage"))
			)
			for slab in MOQ_SLABS
		},
	)


def _record_value(record, fieldname, default=None):
	if isinstance(record, dict):
		return record.get(fieldname, default)
	return getattr(record, fieldname, default)


def _import_fields(item, settings=None):
	settings = settings or get_costing_settings()
	price_rmb = flt(_record_value(item, "custom_price_in_rmb"))
	rate_override = flt(_record_value(item, "custom_rmb_to_inr_rate"))
	effective_rate = effective_exchange_rate(
		settings.default_rmb_to_inr_rate,
		rate_override,
		settings.use_global_rmb_to_inr_rate,
	)
	calculation = calculate_import_cost(
		price_rmb,
		effective_rate,
		_record_value(item, "custom_custom_duty"),
		settings.precision,
	)
	return frappe._dict(
		calculation, effective_rate=effective_rate, available=bool(price_rmb and effective_rate)
	)


def get_approved_price_book_cost(item_code, qty=None, as_of=None):
	"""Return the latest effective, MD-approved rate for an item.

	Within that price-book revision, a matching quantity range wins; then the
	preferred vendor wins; then the lowest company-currency rate wins.
	"""
	if not item_code or not frappe.db.exists("DocType", "RM Price Book"):
		return None
	as_of = getdate(as_of or nowdate())
	rows = frappe.db.sql(
		"""SELECT i.name AS row_name, i.idx, i.base_rate AS rate,
				  i.min_qty, i.max_qty, i.preferred, i.supplier,
				  p.name AS price_book, p.effective_from, p.modified
			 FROM `tabRM Price Book Item` i
			 JOIN `tabRM Price Book` p ON p.name = i.parent
			WHERE i.item_code = %(item_code)s
			  AND i.base_rate > 0
			  AND p.docstatus = 1
			  AND (p.effective_from IS NULL OR p.effective_from <= %(as_of)s)
			ORDER BY p.effective_from DESC, p.modified DESC, i.idx ASC""",
		{"item_code": item_code, "as_of": as_of},
		as_dict=True,
	)
	if not rows:
		return None
	latest_book = rows[0].price_book
	choice = select_price_book_row([row for row in rows if row.price_book == latest_book], qty)
	if not choice:
		return None
	return frappe._dict(
		rate=round_cost(choice.rate, get_costing_settings().precision),
		source=SOURCE_PRICE_BOOK,
		reference=f"{choice.price_book} / {choice.row_name}",
		price_book=choice.price_book,
		row_name=choice.row_name,
	)


def resolve_item_cost(item_code, qty=None, item_doc=None, settings=None):
	"""Resolve one commercial unit rate using the documented source precedence."""
	settings = settings or get_costing_settings()
	book_cost = get_approved_price_book_cost(item_code, qty)
	if book_cost:
		return book_cost

	item = item_doc
	if item is None:
		item = (
			frappe.db.get_value(
				"Item",
				item_code,
				[
					"custom_price_in_rmb",
					"custom_rmb_to_inr_rate",
					"custom_custom_duty",
					"custom_last_purchase_cost",
					"valuation_rate",
				],
				as_dict=True,
			)
			or frappe._dict()
		)

	import_cost = _import_fields(item, settings)
	if import_cost.available:
		return frappe._dict(
			rate=import_cost.landed_cost,
			source=SOURCE_IMPORT,
			reference=f"RMB {flt(_record_value(item, 'custom_price_in_rmb')):g} x INR {import_cost.effective_rate:g}",
		)

	last_purchase_cost = flt(_record_value(item, "custom_last_purchase_cost"))
	if last_purchase_cost > 0:
		return frappe._dict(
			rate=round_cost(last_purchase_cost, settings.precision),
			source=SOURCE_PURCHASE,
			reference="Latest submitted Purchase Receipt",
		)

	valuation_rate = flt(_record_value(item, "valuation_rate"))
	if valuation_rate > 0:
		return frappe._dict(
			rate=round_cost(valuation_rate, settings.precision),
			source=SOURCE_VALUATION,
			reference="Item.valuation_rate",
		)

	return frappe._dict(rate=0.0, source=SOURCE_MISSING, reference="No usable cost source")


def _set_item_snapshot(doc, resolution, settings=None):
	settings = settings or get_costing_settings()
	new_rate = round_cost(resolution.rate, settings.precision)
	changed = any(
		(
			round_cost(doc.get("custom_costing_rate"), settings.precision) != new_rate,
			(doc.get("custom_costing_rate_source") or "") != resolution.source,
			(doc.get("custom_costing_rate_reference") or "") != resolution.reference,
		)
	)
	doc.set("custom_costing_rate", new_rate)
	doc.set("custom_costing_rate_source", resolution.source)
	doc.set("custom_costing_rate_reference", resolution.reference)
	if changed:
		doc.set("custom_costing_rate_updated_on", now_datetime())
	if (
		settings.sync_costing_rate_to_valuation_rate
		and new_rate > 0
		and resolution.source != SOURCE_VALUATION
	):
		doc.set("valuation_rate", new_rate)
	return changed


def item_validate(doc, method=None):
	"""Calculate landed import fields and snapshot the authoritative cost source."""
	settings = get_costing_settings()
	import_cost = _import_fields(doc, settings)
	doc.set("custom_effective_rmb_to_inr_rate", import_cost.effective_rate)
	doc.set("custom_price_in_inr", import_cost.price_in_inr if import_cost.available else 0)
	doc.set("custom_basic_custom_duty", import_cost.duty_amount if import_cost.available else 0)
	resolution = resolve_item_cost(doc.name, item_doc=doc, settings=settings)
	_set_item_snapshot(doc, resolution, settings)


def refresh_item_cost_snapshot(item_code):
	"""Refresh persisted derived fields without running a full Item save."""
	if not item_code or not frappe.db.exists("Item", item_code):
		return None
	settings = get_costing_settings()
	item = frappe.get_doc("Item", item_code)
	import_cost = _import_fields(item, settings)
	item.set("custom_effective_rmb_to_inr_rate", import_cost.effective_rate)
	item.set("custom_price_in_inr", import_cost.price_in_inr if import_cost.available else 0)
	item.set("custom_basic_custom_duty", import_cost.duty_amount if import_cost.available else 0)
	resolution = resolve_item_cost(item_code, item_doc=item, settings=settings)
	_set_item_snapshot(item, resolution, settings)
	values = {
		"custom_effective_rmb_to_inr_rate": item.custom_effective_rmb_to_inr_rate,
		"custom_price_in_inr": item.custom_price_in_inr,
		"custom_basic_custom_duty": item.custom_basic_custom_duty,
	}
	values.update({fieldname: item.get(fieldname) for fieldname in ITEM_COST_FIELDS})
	if settings.sync_costing_rate_to_valuation_rate and resolution.source != SOURCE_VALUATION:
		values["valuation_rate"] = resolution.rate
	frappe.db.set_value("Item", item_code, values, update_modified=False)
	return resolution


def item_on_update(doc, method=None):
	"""Refresh every dependent BOM when the resolved commercial cost changes."""
	try:
		if doc.has_value_changed("custom_costing_rate"):
			recompute_boms_for_items([doc.name])
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Costing auto-sync: Item refresh failed")


def _find_active_bom(item_code, exclude_bom=None, parent_only=False):
	if not item_code:
		return None
	filters = {"item": item_code, "is_active": 1, "docstatus": 1}
	if parent_only:
		filters["custom_bom_type"] = "Parent BOM"
	default_bom = frappe.db.get_value("Item", item_code, "default_bom")
	if default_bom and default_bom != exclude_bom:
		is_valid = frappe.db.get_value(
			"BOM", default_bom, ["is_active", "docstatus", "custom_bom_type"], as_dict=True
		)
		if is_valid and cint(is_valid.is_active) and cint(is_valid.docstatus) == 1:
			if not parent_only or is_valid.custom_bom_type == "Parent BOM":
				return default_bom
	rows = frappe.get_all(
		"BOM",
		filters=filters,
		fields=["name"],
		order_by="is_default DESC, modified DESC",
		limit=5,
	)
	return next((row.name for row in rows if row.name != exclude_bom), None)


def _child_bom_for_row(row, parent_bom_name=None):
	explicit = (row.get("bom_no") or "").strip()
	if explicit and explicit != parent_bom_name:
		return explicit, "Child BOM"
	linked = _find_active_bom(row.get("item_code"), exclude_bom=parent_bom_name)
	return (linked, "Default BOM") if linked else (None, None)


def _row_rate(row, parent_bom_name=None, rate_cache=None):
	child_bom, source = _child_bom_for_row(row, parent_bom_name)
	if child_bom:
		child = frappe.db.get_value(
			"BOM",
			child_bom,
			["custom_sub_bom_total", "custom_bom_cost", "is_active", "docstatus"],
			as_dict=True,
		)
		if child and cint(child.docstatus) == 1:
			rate = flt(child.custom_sub_bom_total) or flt(child.custom_bom_cost)
			return frappe._dict(
				rate=round_cost(rate, get_costing_settings().precision),
				source=source,
				reference=child_bom,
			)

	item_code = row.get("item_code")
	rate_cache = rate_cache if rate_cache is not None else {}
	if item_code not in rate_cache:
		rate_cache[item_code] = resolve_item_cost(item_code)
	return rate_cache[item_code]


def _manual_moq_percentage(doc, slab, settings):
	value = doc.get(f"custom_{slab}_moq_percentage")
	return settings.default_moq_percentages[slab] if value in (None, "") else flt(value)


def compute_bom_costing(doc):
	"""Set row rates plus all derived, per-unit custom BOM costing fields."""
	settings = get_costing_settings()
	raw_batch_total = 0.0
	rate_cache = {}
	missing_items = []
	for row in doc.get("items") or []:
		resolution = _row_rate(row, doc.get("name"), rate_cache)
		row.set("rate", resolution.rate)
		row.set("amount", round_cost(flt(row.get("qty")) * resolution.rate, settings.precision))
		row.set("custom_cost_source", resolution.source)
		row.set("custom_cost_reference", resolution.reference)
		raw_batch_total += row.amount
		if flt(resolution.rate) <= 0:
			missing_items.append(row.get("item_code") or f"Row {row.get('idx')}")

	layers = [(percentage_field, doc.get(percentage_field)) for percentage_field, *_ in COST_LAYERS]
	moq_percentages = {slab: _manual_moq_percentage(doc, slab, settings) for slab in MOQ_SLABS}
	breakdown = calculate_bom_cost(
		raw_materials_batch_total=raw_batch_total,
		output_qty=doc.get("quantity"),
		bom_type=doc.get("custom_bom_type") or "Parent BOM",
		conversion_cost=doc.get("custom_conversion_cost"),
		inward_transport_cost=doc.get("custom_inward_transport_cost"),
		factory_overheads=doc.get("custom_factory_overheads"),
		layers=layers,
		moq_percentages=moq_percentages,
		precision=settings.precision,
	)
	doc.set("custom_raw_materials_batch_total", breakdown["raw_materials_batch_total"])
	doc.set("custom_raw_materials_total", breakdown["raw_materials_unit_total"])
	doc.set("custom_sub_bom_total", breakdown["rollup_cost"])
	doc.set("custom_bom_cost", breakdown["final_cost"])
	doc.set("custom_costing_status", "Missing Costs" if missing_items else "Complete")
	doc.set("custom_missing_cost_items", ", ".join(dict.fromkeys(missing_items)))

	for percentage_field, base_field, value_field, total_field in COST_LAYERS:
		layer = breakdown["layers"].get(percentage_field, {})
		doc.set(base_field, layer.get("base", 0))
		doc.set(value_field, layer.get("value", 0))
		doc.set(total_field, layer.get("total", 0))
	for slab in MOQ_SLABS:
		doc.set(f"custom_{slab}_moq_price", breakdown["moq_prices"].get(slab, 0))
	return breakdown


def bom_validate(doc, method=None):
	compute_bom_costing(doc)


def _persist_bom_costing(doc):
	"""Persist a recomputed submitted BOM without re-entering validation."""
	row_meta = frappe.get_meta("BOM Item")
	for row in doc.get("items") or []:
		row.db_set("rate", row.rate, update_modified=False)
		row.db_set("amount", row.amount, update_modified=False)
		for fieldname in ("custom_cost_source", "custom_cost_reference"):
			if row_meta.has_field(fieldname):
				row.db_set(fieldname, row.get(fieldname), update_modified=False)
	for fieldname in DERIVED_BOM_FIELDS:
		if doc.meta.has_field(fieldname):
			doc.db_set(fieldname, doc.get(fieldname), update_modified=False)


def bom_on_submit(doc, method=None):
	_cascade_to_parents(doc.name, doc.item)


def bom_on_update_after_submit(doc, method=None):
	compute_bom_costing(doc)
	_persist_bom_costing(doc)
	_cascade_to_parents(doc.name, doc.item)


def bom_on_cancel(doc, method=None):
	_cascade_to_parents(doc.name, doc.item)


def _parent_bom_names(bom_name, item_code):
	parents = set(
		frappe.get_all(
			"BOM Item",
			filters={"bom_no": bom_name, "parenttype": "BOM", "docstatus": 1},
			pluck="parent",
			distinct=True,
		)
	)
	if item_code:
		item_rows = frappe.get_all(
			"BOM Item",
			filters={"item_code": item_code, "parenttype": "BOM", "docstatus": 1},
			fields=["parent", "bom_no"],
		)
		parents.update(row.parent for row in item_rows if not row.bom_no)
	parents.discard(bom_name)
	return parents


def _cascade_to_parents(bom_name, item_code=None, processed=None):
	"""Breadth-first cascade through explicit and item-only parent links."""
	processed = processed if processed is not None else set()
	expanded = set()
	queue = [(bom_name, item_code)]
	while queue:
		child_name, child_item = queue.pop(0)
		if child_name in expanded:
			continue
		expanded.add(child_name)
		for parent_name in _parent_bom_names(child_name, child_item):
			if parent_name in processed:
				continue
			try:
				parent = frappe.get_doc("BOM", parent_name)
				if not cint(parent.is_active) or cint(parent.docstatus) != 1:
					continue
				compute_bom_costing(parent)
				_persist_bom_costing(parent)
				processed.add(parent_name)
				queue.append((parent_name, parent.item))
			except Exception:
				frappe.log_error(
					frappe.get_traceback(), f"Costing cascade failed for parent BOM {parent_name}"
				)
	return processed


def recompute_boms_for_items(item_codes, processed=None):
	"""Recompute direct consumers and every active submitted ancestor BOM."""
	processed = processed if processed is not None else set()
	item_codes = sorted({item_code for item_code in (item_codes or []) if item_code})
	if not item_codes:
		return processed
	direct_boms = frappe.get_all(
		"BOM Item",
		filters={"item_code": ["in", item_codes], "parenttype": "BOM", "docstatus": 1},
		pluck="parent",
		distinct=True,
	)
	for bom_name in sorted(set(direct_boms)):
		if bom_name in processed:
			continue
		try:
			doc = frappe.get_doc("BOM", bom_name)
			if not cint(doc.is_active) or cint(doc.docstatus) != 1:
				continue
			compute_bom_costing(doc)
			_persist_bom_costing(doc)
			processed.add(bom_name)
			_cascade_to_parents(bom_name, doc.item, processed)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Costing auto-sync failed for BOM {bom_name}")
	return processed


def get_bom_moq_price(item_code, moq):
	"""Resolve a quotation base from the deterministic active Parent BOM."""
	slab = {1000: "1k", 3000: "3k", 6000: "6k", 10000: "10k"}.get(cint(moq))
	if not slab:
		return None
	bom_name = _find_active_bom(item_code, parent_only=True)
	if not bom_name:
		return None
	bom = frappe.db.get_value(
		"BOM",
		bom_name,
		[f"custom_{slab}_moq_price", "custom_bom_cost", "custom_costing_status"],
		as_dict=True,
	)
	if not bom:
		return None
	if bom.custom_costing_status == "Missing Costs":
		return None
	return flt(bom.get(f"custom_{slab}_moq_price")) or flt(bom.custom_bom_cost) or None


def on_purchase_receipt(doc, method=None):
	"""Keep the last actual receipt cost as a fallback, then refresh dependants."""
	try:
		touched = set()
		settings = get_costing_settings()
		for row in doc.get("items") or []:
			item_code = row.get("item_code")
			rate = flt(row.get("valuation_rate")) or flt(row.get("base_rate")) or flt(row.get("rate"))
			if not item_code or rate <= 0:
				continue
			frappe.db.set_value(
				"Item",
				item_code,
				"custom_last_purchase_cost",
				round_cost(rate, settings.precision),
				update_modified=False,
			)
			refresh_item_cost_snapshot(item_code)
			touched.add(item_code)
		recompute_boms_for_items(touched)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Costing auto-sync: Purchase Receipt failed")


def on_stock_entry(doc, method=None):
	try:
		purpose = doc.get("purpose") or doc.get("stock_entry_type")
		if purpose != "Manufacture":
			return
		items = {row.get("item_code") for row in (doc.get("items") or []) if row.get("item_code")}
		recompute_boms_for_items(items)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Costing auto-sync: Stock Entry failed")


def sync_item_costs(item_codes):
	"""Refresh item snapshots and BOMs after price-book submit/cancel."""
	item_codes = sorted({item_code for item_code in (item_codes or []) if item_code})
	for item_code in item_codes:
		refresh_item_cost_snapshot(item_code)
	recompute_boms_for_items(item_codes)


def on_costing_settings_update(doc, method=None):
	tracked = (
		"default_rmb_to_inr_rate",
		"use_global_rmb_to_inr_rate",
		"sync_costing_rate_to_valuation_rate",
		"default_1k_moq_percentage",
		"default_3k_moq_percentage",
		"default_6k_moq_percentage",
		"default_10k_moq_percentage",
	)
	if doc.is_new() or any(doc.has_value_changed(fieldname) for fieldname in tracked):
		schedule_costing_rebuild()


def schedule_costing_rebuild():
	"""Queue a full bottom-up rebuild after settings/schema changes."""
	try:
		frappe.enqueue(
			"lumirise_custom.costing.rebuild_all_costing",
			queue="long",
			enqueue_after_commit=True,
			job_name="lumirise-costing-rebuild",
			deduplicate=True,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Could not queue full costing rebuild")


def rebuild_all_costing():
	"""Refresh all item snapshots and rebuild active BOMs child-first."""
	item_codes = frappe.get_all("Item", filters={"disabled": 0}, pluck="name")
	for item_code in item_codes:
		try:
			refresh_item_cost_snapshot(item_code)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Costing rebuild failed for Item {item_code}")

	bom_names = set(frappe.get_all("BOM", filters={"is_active": 1, "docstatus": 1}, pluck="name"))
	processed = set()
	stack = set()

	def rebuild_bom(bom_name):
		if bom_name in processed:
			return
		if bom_name in stack:
			frappe.log_error(f"BOM cycle includes {bom_name}", "Costing rebuild: BOM cycle")
			return
		stack.add(bom_name)
		doc = frappe.get_doc("BOM", bom_name)
		for row in doc.get("items") or []:
			child_bom, _source = _child_bom_for_row(row, doc.name)
			if child_bom and child_bom in bom_names:
				rebuild_bom(child_bom)
		compute_bom_costing(doc)
		_persist_bom_costing(doc)
		stack.discard(bom_name)
		processed.add(bom_name)

	for bom_name in bom_names:
		try:
			rebuild_bom(bom_name)
		except Exception:
			stack.discard(bom_name)
			frappe.log_error(frappe.get_traceback(), f"Costing rebuild failed for BOM {bom_name}")
	return {"items": len(item_codes), "boms": len(processed)}


@frappe.whitelist()
def request_costing_rebuild():
	frappe.only_for("System Manager")
	schedule_costing_rebuild()
	return {"queued": True}


@frappe.whitelist()
def preview_item_costing(doc):
	frappe.has_permission("Item", ptype="read", throw=True)
	preview = frappe.get_doc(frappe.parse_json(doc))
	item_validate(preview)
	fields = (
		"custom_effective_rmb_to_inr_rate",
		"custom_price_in_inr",
		"custom_basic_custom_duty",
		"custom_costing_rate",
		"custom_costing_rate_source",
		"custom_costing_rate_reference",
		"valuation_rate",
	)
	return {fieldname: preview.get(fieldname) for fieldname in fields}


@frappe.whitelist()
def preview_bom_costing(doc):
	frappe.has_permission("BOM", ptype="read", throw=True)
	preview = frappe.get_doc(frappe.parse_json(doc))
	compute_bom_costing(preview)
	return {
		"fields": {fieldname: preview.get(fieldname) for fieldname in DERIVED_BOM_FIELDS},
		"items": [
			{
				"name": row.name,
				"rate": row.rate,
				"amount": row.amount,
				"custom_cost_source": row.get("custom_cost_source"),
				"custom_cost_reference": row.get("custom_cost_reference"),
			}
			for row in preview.get("items") or []
		],
	}
