"""Sales Platform pricing engine.

1:1 port of the web platform's src/lib/pricing.ts (generatePriceSheet,
calculateApprovalPrice) with one upgrade: the base light price resolves from
the item's active costed Parent BOM first (MOQ slab fields), falling back to
the migrated Lumirise Base Price master. Rounding everywhere is the
platform's roundApprovalPrice: round to 3 decimals.
"""

import frappe
from frappe.utils import flt

from lumirise_custom.costing import get_bom_moq_price

QUANTITY_TIERS = [
	{"moq": 1000, "label": "1000-2999"},
	{"moq": 3000, "label": "3000-5999"},
	{"moq": 6000, "label": "6000-9999"},
	{"moq": 10000, "label": "10000+"},
]

NO_MONO_BOX = "No Mono Box"
NO_MASTER_BOX = "No Master Box"
NO_TRANSPORT = "No Transport"


def r3(value):
	return flt(value, 3)


def get_settings():
	s = frappe.get_cached_doc("Sales Platform Settings")
	return frappe._dict(
		no_master_box_extra_cost=flt(s.no_master_box_extra_cost) or 0.8,
		profit_fallback_finish=s.profit_fallback_finish or "UV DRIPOFF SPOT",
		approval_window_days=int(s.approval_window_days or 7),
		min_agreed_qty=int(s.min_agreed_qty or 1000),
	)


def moq_for_quantity(quantity):
	"""Platform getMoqForQuantity: tier floor for an agreed quantity."""
	quantity = flt(quantity)
	if quantity < 1000:
		return None
	if quantity < 3000:
		return 1000
	if quantity < 6000:
		return 3000
	if quantity < 10000:
		return 6000
	return 10000


def _best_moq_match(rows, moq):
	"""Highest MOQ <= requested; else the lowest tier on record."""
	if not rows:
		return None
	smaller = [row for row in rows if int(row.moq) <= int(moq)]
	if smaller:
		return max(smaller, key=lambda row: int(row.moq))
	return min(rows, key=lambda row: int(row.moq))


def get_base_price(item, moq):
	"""BOM MOQ slab first, then Lumirise Base Price (best-MOQ match)."""
	bom_price = get_bom_moq_price(item, moq)
	if bom_price:
		return r3(bom_price), "BOM"

	rows = frappe.get_all(
		"Lumirise Base Price", filters={"item": item}, fields=["moq", "price"]
	)
	match = _best_moq_match(rows, moq)
	return (r3(match.price), "Base Price") if match else (0.0, "None")


def get_mono_box_data(item, finish, moq):
	"""purchase/selling/profit for item+finish at best MOQ match, or Nones."""
	if not finish or finish in (NO_MONO_BOX, "No Box"):
		return frappe._dict(purchase_price=None, selling_price=None, profit_price=None)
	rows = frappe.get_all(
		"Mono Box Pricing",
		filters={"item": item, "box_finish": finish},
		fields=["moq", "purchase_price", "selling_price", "profit_price"],
	)
	match = _best_moq_match(rows, moq)
	if not match:
		return frappe._dict(purchase_price=None, selling_price=None, profit_price=None)
	return frappe._dict(
		purchase_price=flt(match.purchase_price),
		selling_price=flt(match.selling_price),
		profit_price=flt(match.profit_price),
	)


def get_no_box_profit(item, moq, settings=None):
	"""Profit for 'no mono box': fallback finish first, then any finish with profit > 0."""
	settings = settings or get_settings()
	data = get_mono_box_data(item, settings.profit_fallback_finish, moq)
	if data.profit_price:
		return data.profit_price

	rows = frappe.get_all(
		"Mono Box Pricing",
		filters={"item": item, "profit_price": (">", 0)},
		fields=["moq", "profit_price"],
	)
	match = _best_moq_match(rows, moq)
	return flt(match.profit_price) if match else 0.0


def get_master_box_data(item, finish, caselot):
	"""Exact match on item+finish+caselot. Selected-but-missing returns zeros
	(platform behaviour); no selection returns Nones."""
	if not finish or finish in (NO_MASTER_BOX, "None") or not caselot:
		return frappe._dict(price=None, cost_per_light=None)
	row = frappe.db.get_value(
		"Master Box Pricing",
		{"item": item, "box_finish": finish, "caselot": int(caselot)},
		["purchase_price", "price_per_unit"],
		as_dict=True,
	)
	if not row:
		return frappe._dict(price=0.0, cost_per_light=0.0)
	return frappe._dict(
		price=flt(row.purchase_price), cost_per_light=r3(row.price_per_unit)
	)


def get_transport_cost(item, transport_type, zone):
	if not transport_type or not zone:
		return 0.0
	return flt(
		frappe.db.get_value(
			"Transport Pricing",
			{"item": item, "transport_type": transport_type, "transport_zone": zone},
			"cost_per_unit",
		)
	)


def get_credit_percentage(credit_days):
	if not credit_days:
		return 0.0
	return flt(
		frappe.db.get_value(
			"Sales Credit Term",
			{"payment_type": "Credit", "credit_days": int(credit_days)},
			"percentage",
		)
	)


def item_caselots_with_records(item, finish, caselots):
	"""Platform productCaselots filter: keep only caselots that actually have
	a Master Box Pricing record for this item+finish."""
	kept = []
	for caselot in caselots:
		if frappe.db.exists(
			"Master Box Pricing",
			{"item": item, "box_finish": finish, "caselot": int(caselot)},
		):
			kept.append(int(caselot))
	return kept


def generate_rows(sheet):
	"""Build Price Sheet Row dicts for a Price Sheet document (config on doc).

	Mirrors generatePriceSheet(): rows per item x caselot x tier x finish,
	plus one baseline row per item x caselot x tier (finish = No Mono Box).
	"""
	settings = get_settings()

	items = [p.item for p in (sheet.products or [])]
	finishes = [f.box_finish for f in (sheet.mono_box_finishes or [])]
	include_transport = sheet.delivery_type == "Transport"
	has_master_box = bool(sheet.master_box_finish)
	has_credit = sheet.payment_type == "Credit" and flt(sheet.credit_days) > 0
	credit_pct = get_credit_percentage(sheet.credit_days) if has_credit else 0.0

	caselots = []
	if has_master_box and (sheet.master_box_caselots or "").strip():
		for part in str(sheet.master_box_caselots).split(","):
			part = part.strip()
			if part.isdigit():
				caselots.append(int(part))
	caselots = caselots or [None]

	def credit_loaded(subtotal):
		added = r3(subtotal * credit_pct / 100.0) if has_credit else 0.0
		return added, r3(subtotal + added)

	rows = []
	for item in items:
		item_caselots = caselots
		if has_master_box:
			real = [c for c in caselots if c]
			item_caselots = item_caselots_with_records(item, sheet.master_box_finish, real)
			if not item_caselots:
				continue  # platform: no master-box record at all -> no rows for item

		for caselot in item_caselots:
			master = get_master_box_data(item, sheet.master_box_finish, caselot)
			master_cost = flt(master.cost_per_light)

			for tier in QUANTITY_TIERS:
				moq, label = tier["moq"], tier["label"]
				base_price, source = get_base_price(item, moq)
				transport = (
					get_transport_cost(item, sheet.transport_type, sheet.transport_zone)
					if include_transport
					else 0.0
				)
				packaging = master_cost if has_master_box else settings.no_master_box_extra_cost

				baseline_profit = get_no_box_profit(item, moq, settings)
				baseline_total = (
					r3(base_price + baseline_profit + settings.no_master_box_extra_cost)
					if baseline_profit > 0
					else None
				)
				no_mono_subtotal = (
					base_price
					+ baseline_profit
					+ (master_cost if has_master_box else 0.0)
					+ transport
				)
				no_mono_added, no_mono_total = credit_loaded(no_mono_subtotal)
				common = {
					"item": item,
					"moq": moq,
					"moq_label": label,
					"caselot": caselot,
					"base_price": base_price,
					"price_source": source,
					"master_box_finish": sheet.master_box_finish if has_master_box else None,
					"master_box_cost_per_light": master.cost_per_light,
					"transport_cost": transport if include_transport else 0.0,
					"credit_percentage": credit_pct,
					"baseline_total": baseline_total,
					"total_without_mono_box": no_mono_total if baseline_profit > 0 else None,
				}

				# Baseline row (no mono box)
				rows.append(
					dict(
						common,
						box_finish=NO_MONO_BOX,
						mono_profit_price=baseline_profit or None,
						credit_added=no_mono_added if baseline_profit > 0 else None,
						total=no_mono_total if baseline_profit > 0 else None,
					)
				)

				# One row per requested finish
				for finish in finishes:
					mono = get_mono_box_data(item, finish, moq)
					has_data = mono.selling_price is not None
					selling = flt(mono.selling_price)
					subtotal = base_price + selling + packaging + transport
					added, total = credit_loaded(subtotal)
					rows.append(
						dict(
							common,
							box_finish=finish,
							mono_purchase_price=mono.purchase_price,
							mono_selling_price=selling if has_data else None,
							mono_profit_price=mono.profit_price or 0,
							credit_added=added,
							total=total,
						)
					)
	return rows


def calculate_approval_price(item, moq, mono_box_finish, master_box_finish,
		master_box_caselot, transport_mode, transport_type, transport_zone,
		credit_days):
	"""Port of calculateApprovalPrice(): single-line breakdown for approval."""
	settings = get_settings()
	if not moq:
		return frappe._dict(
			base_price=None, mono_box_price=None, master_box_price=None,
			transport_price=None, credit_price=None, calculated_price=None,
		)

	base_price, _source = get_base_price(item, moq)

	if not mono_box_finish or mono_box_finish in (NO_MONO_BOX, "No Box"):
		mono_price = r3(get_no_box_profit(item, moq, settings))
	else:
		mono_price = r3(flt(get_mono_box_data(item, mono_box_finish, moq).selling_price))

	master = get_master_box_data(item, master_box_finish, master_box_caselot)
	master_price = master.cost_per_light

	transport_price = None
	if transport_mode != NO_TRANSPORT and transport_type and transport_zone:
		transport_price = r3(get_transport_cost(item, transport_type, transport_zone))

	credit_pct = get_credit_percentage(credit_days)
	packaging = master_price if master_price is not None else settings.no_master_box_extra_cost
	subtotal = r3(base_price + mono_price + packaging + flt(transport_price))
	credit_price = r3(subtotal * credit_pct / 100.0) if credit_pct > 0 else None

	return frappe._dict(
		base_price=base_price,
		mono_box_price=mono_price,
		master_box_price=master_price,
		transport_price=transport_price,
		credit_price=credit_price,
		calculated_price=r3(subtotal + flt(credit_price)),
	)
