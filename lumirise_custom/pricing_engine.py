"""Sales Platform pricing engine.

1:1 port of the web platform's src/lib/pricing.ts (generatePriceSheet,
calculateApprovalPrice) with one upgrade: the base light price resolves from
the item's active costed Parent BOM first (MOQ slab fields), falling back to
the migrated Lumirise Base Price master. Rounding everywhere is the
platform's roundApprovalPrice: round to 3 decimals.
"""

import frappe
from frappe import _
from frappe.utils import flt

from lumirise_custom.costing import get_bom_moq_price
from lumirise_custom.costing_math import round_cost

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
	return round_cost(value, 3)


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
		return frappe._dict(
			purchase_price=None, selling_price=None, profit_price=None, found=False
		)
	rows = frappe.get_all(
		"Mono Box Pricing",
		filters={"item": item, "box_finish": finish},
		fields=["moq", "purchase_price", "selling_price", "profit_price"],
	)
	match = _best_moq_match(rows, moq)
	if not match:
		return frappe._dict(
			purchase_price=None, selling_price=None, profit_price=None, found=False
		)
	return frappe._dict(
		purchase_price=flt(match.purchase_price),
		selling_price=flt(match.selling_price),
		profit_price=flt(match.profit_price),
		found=True,
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
	"""Exact item/finish/caselot match, with an explicit found flag."""
	if not finish or finish in (NO_MASTER_BOX, "None") or not caselot:
		return frappe._dict(price=None, cost_per_light=None, found=False)
	row = frappe.db.get_value(
		"Master Box Pricing",
		{"item": item, "box_finish": finish, "caselot": int(caselot)},
		["purchase_price", "price_per_unit"],
		as_dict=True,
	)
	if not row:
		return frappe._dict(price=None, cost_per_light=None, found=False)
	return frappe._dict(
		price=flt(row.purchase_price), cost_per_light=r3(row.price_per_unit), found=True
	)


def get_transport_data(item, transport_type, zone):
	if not transport_type or not zone:
		return frappe._dict(cost_per_unit=None, found=False)
	value = frappe.db.get_value(
		"Transport Pricing",
		{"item": item, "transport_type": transport_type, "transport_zone": zone},
		"cost_per_unit",
	)
	return frappe._dict(
		cost_per_unit=r3(value) if value is not None else None,
		found=value is not None,
	)


def get_transport_cost(item, transport_type, zone):
	return flt(get_transport_data(item, transport_type, zone).cost_per_unit)


def get_credit_data(credit_days):
	if not credit_days:
		return frappe._dict(percentage=0.0, found=True)
	value = frappe.db.get_value(
		"Sales Credit Term",
		{"payment_type": "Credit", "credit_days": int(credit_days)},
		"percentage",
	)
	return frappe._dict(
		percentage=flt(value) if value is not None else None,
		found=value is not None,
	)


def get_credit_percentage(credit_days):
	return flt(get_credit_data(credit_days).percentage)


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


def _parse_caselots(value):
	values = []
	for part in str(value or "").split(","):
		part = part.strip()
		if part.isdigit() and int(part) > 0:
			values.append(int(part))
	return sorted(set(values))


def get_master_box_caselots(item, finish):
	"""Every available caselot for one product/finish, in display order."""
	if not finish or finish in (NO_MASTER_BOX, "None"):
		return []
	return sorted(
		{
			int(value)
			for value in frappe.get_all(
				"Master Box Pricing",
				filters={"item": item, "box_finish": finish},
				pluck="caselot",
			)
			if value
		}
	)


def get_item_mono_finishes(item):
	"""All mono-box finishes that are genuinely priced for an item."""
	return frappe.get_all(
		"Mono Box Pricing",
		filters={"item": item},
		pluck="box_finish",
		distinct=True,
		order_by="box_finish",
	)


def _configuration_contexts(sheet):
	"""Normalise the new queue and legacy single-config form into item contexts."""
	if sheet.get("configurations"):
		for config in sheet.configurations:
			master_finish = config.master_box_finish or None
			caselots = _parse_caselots(config.master_box_caselots)
			if master_finish and not caselots:
				caselots = get_master_box_caselots(config.item, master_finish)
			yield frappe._dict(
				configuration_group=config.configuration_group,
				item=config.item,
				finishes=get_item_mono_finishes(config.item),
				master_box_finish=master_finish,
				caselots=caselots,
				delivery_type=config.delivery_type or "Ex-Factory",
				transport_type=config.transport_type,
				transport_zone=config.transport_zone,
				payment_type=config.payment_type or "Advance",
				credit_days=int(config.credit_days or 0),
			)
		return

	finishes = [row.box_finish for row in (sheet.get("mono_box_finishes") or [])]
	caselots = _parse_caselots(sheet.get("master_box_caselots"))
	for product in sheet.get("products") or []:
		yield frappe._dict(
			configuration_group="Legacy",
			item=product.item,
			finishes=finishes,
			master_box_finish=sheet.get("master_box_finish"),
			caselots=caselots,
			delivery_type=sheet.get("delivery_type") or "Ex-Factory",
			transport_type=sheet.get("transport_type"),
			transport_zone=sheet.get("transport_zone"),
			payment_type=sheet.get("payment_type") or "Advance",
			credit_days=int(sheet.get("credit_days") or 0),
		)


def _validated_context(context, settings):
	"""Reject incomplete masters before a customer can receive an understated price."""
	if not context.item:
		frappe.throw(_("Every quotation configuration must have a product"))

	if context.master_box_finish:
		available = get_master_box_caselots(context.item, context.master_box_finish)
		if not available:
			frappe.throw(
				_("{0}: no Master Box Pricing exists for finish {1}").format(
					context.item, context.master_box_finish
				)
			)
		requested = context.caselots or available
		missing = sorted(set(requested) - set(available))
		if missing:
			frappe.throw(
				_("{0}: no Master Box Pricing for caselot(s) {1} with finish {2}").format(
					context.item, ", ".join(str(value) for value in missing), context.master_box_finish
				)
			)
		context.caselots = requested
	else:
		context.caselots = [None]

	if context.delivery_type == "Transport":
		if not context.transport_type or not context.transport_zone:
			frappe.throw(
				_("{0}: choose both Transport Type and Transport Zone").format(context.item)
			)
		transport = get_transport_data(
			context.item, context.transport_type, context.transport_zone
		)
		if not transport.found:
			frappe.throw(
				_("{0}: transport price is missing for {1}, zone {2}").format(
					context.item, context.transport_type, context.transport_zone
				)
			)

	if context.payment_type == "Credit":
		if context.credit_days <= 0:
			frappe.throw(_("{0}: choose Credit Days").format(context.item))
		if not get_credit_data(context.credit_days).found:
			frappe.throw(
				_("{0}: no Sales Credit Term exists for {1} days").format(
					context.item, context.credit_days
				)
			)

	for tier in QUANTITY_TIERS:
		base_price, _source = get_base_price(context.item, tier["moq"])
		if base_price <= 0:
			frappe.throw(
				_("{0}: base price is missing for MOQ {1}. Add a costed Parent BOM or Lumirise Base Price.").format(
					context.item, tier["moq"]
				)
			)
		if get_no_box_profit(context.item, tier["moq"], settings) <= 0:
			frappe.throw(
				_("{0}: no positive mono-box profit fallback exists for MOQ {1}").format(
					context.item, tier["moq"]
				)
			)

	return context


def generate_rows(sheet):
	"""Generate the original platform grid from queued or legacy configuration."""
	settings = get_settings()

	rows = []
	for raw_context in _configuration_contexts(sheet):
		context = _validated_context(raw_context, settings)
		item = context.item
		include_transport = context.delivery_type == "Transport"
		has_master_box = bool(context.master_box_finish)
		has_credit = context.payment_type == "Credit" and context.credit_days > 0
		credit_pct = get_credit_percentage(context.credit_days) if has_credit else 0.0

		def credit_loaded(subtotal):
			added = r3(subtotal * credit_pct / 100.0) if has_credit else 0.0
			return added, r3(subtotal + added)

		for caselot in context.caselots:
			master = get_master_box_data(item, context.master_box_finish, caselot)
			master_cost = flt(master.cost_per_light)

			for tier in QUANTITY_TIERS:
				moq, label = tier["moq"], tier["label"]
				base_price, source = get_base_price(item, moq)
				transport = (
					get_transport_cost(item, context.transport_type, context.transport_zone)
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
					"configuration_group": context.configuration_group,
					"item": item,
					"moq": moq,
					"moq_label": label,
					"caselot": caselot,
					"base_price": base_price,
					"price_source": source,
					"master_box_finish": context.master_box_finish if has_master_box else None,
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
				for finish in context.finishes:
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
	"""Port of calculateApprovalPrice(), with missing-master safeguards."""
	settings = get_settings()
	if not moq:
		return frappe._dict(
			base_price=None, mono_box_price=None, master_box_price=None,
			transport_price=None, credit_price=None, calculated_price=None,
		)

	base_price, _source = get_base_price(item, moq)
	if base_price <= 0:
		frappe.throw(
			_("{0}: base price is missing for MOQ {1}").format(item, moq)
		)

	if not mono_box_finish or mono_box_finish in (NO_MONO_BOX, "No Box"):
		mono_price = r3(get_no_box_profit(item, moq, settings))
		if mono_price <= 0:
			frappe.throw(
				_("{0}: no positive mono-box profit fallback exists for MOQ {1}").format(
					item, moq
				)
			)
	else:
		mono = get_mono_box_data(item, mono_box_finish, moq)
		if not mono.found:
			frappe.throw(
				_("{0}: mono-box price is missing for {1}, MOQ {2}").format(
					item, mono_box_finish, moq
				)
			)
		mono_price = r3(mono.selling_price)

	master = get_master_box_data(item, master_box_finish, master_box_caselot)
	if master_box_finish and not master_box_caselot:
		frappe.throw(_("{0}: choose a Master Box Caselot").format(item))
	if master_box_finish and not master.found:
		frappe.throw(
			_("{0}: master-box price is missing for {1}, caselot {2}").format(
				item, master_box_finish, master_box_caselot
			)
		)
	master_price = master.cost_per_light

	transport_price = None
	if transport_mode != NO_TRANSPORT:
		if not transport_type or not transport_zone:
			frappe.throw(
				_("{0}: choose both Transport Type and Transport Zone").format(item)
			)
		transport = get_transport_data(item, transport_type, transport_zone)
		if not transport.found:
			frappe.throw(
				_("{0}: transport price is missing for {1}, zone {2}").format(
					item, transport_type, transport_zone
				)
			)
		transport_price = transport.cost_per_unit

	credit = get_credit_data(credit_days)
	if credit_days and not credit.found:
		frappe.throw(
			_("{0}: no Sales Credit Term exists for {1} days").format(item, credit_days)
		)
	credit_pct = flt(credit.percentage)
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
