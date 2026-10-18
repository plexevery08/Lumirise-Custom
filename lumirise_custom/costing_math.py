"""Pure, deterministic arithmetic for Lumirise item and BOM costing.

This module deliberately has no Frappe imports. Keeping the formula here makes
the server calculation testable and gives every caller the same rounding rule.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def decimal_value(value):
	"""Return a safe Decimal for values arriving from Frappe/JSON."""
	if value in (None, ""):
		return Decimal("0")
	try:
		return Decimal(str(value))
	except InvalidOperation, TypeError, ValueError:
		return Decimal("0")


def round_cost(value, precision=3):
	"""Round monetary values with the usual commercial half-up rule."""
	precision = 3 if precision in (None, "") else int(precision)
	precision = max(0, min(precision, 6))
	quantum = Decimal("1").scaleb(-precision)
	return float(decimal_value(value).quantize(quantum, rounding=ROUND_HALF_UP))


def calculate_import_cost(price_rmb, rmb_to_inr_rate, duty_percent, precision=3):
	"""RMB price -> INR price -> duty -> landed commercial cost."""
	price_in_inr = round_cost(decimal_value(price_rmb) * decimal_value(rmb_to_inr_rate), precision)
	duty_amount = round_cost(
		decimal_value(price_in_inr) * decimal_value(duty_percent) / Decimal("100"),
		precision,
	)
	return {
		"price_in_inr": price_in_inr,
		"duty_amount": duty_amount,
		"landed_cost": round_cost(decimal_value(price_in_inr) + decimal_value(duty_amount), precision),
	}


def effective_exchange_rate(global_rate, item_override=0, enforce_global=True):
	"""Resolve the commercial FX rate while allowing an optional item exception."""
	global_rate = decimal_value(global_rate)
	item_override = decimal_value(item_override)
	if enforce_global and global_rate > 0:
		return float(global_rate)
	return float(item_override or global_rate)


def select_price_book_row(rows, qty=None):
	"""Pick a deterministic row: matching range, preferred vendor, lowest rate.

	All supplied rows must belong to the same approved price-book revision. When
	no range matches (or no quantity is supplied), the preferred/lowest rule is
	still deterministic and avoids an arbitrary database row.
	"""
	rows = list(rows or [])
	if not rows:
		return None

	requested_qty = decimal_value(qty)

	def get(row, key, default=None):
		if isinstance(row, dict):
			return row.get(key, default)
		return getattr(row, key, default)

	def matches(row):
		if requested_qty <= 0:
			return True
		minimum = decimal_value(get(row, "min_qty"))
		maximum = decimal_value(get(row, "max_qty"))
		return not ((minimum > 0 and requested_qty < minimum) or (maximum > 0 and requested_qty > maximum))

	candidates = [row for row in rows if matches(row)] or rows
	return min(
		candidates,
		key=lambda row: (
			0 if int(decimal_value(get(row, "preferred"))) else 1,
			decimal_value(get(row, "rate")),
			int(decimal_value(get(row, "idx"))),
		),
	)


def calculate_bom_cost(
	*,
	raw_materials_batch_total,
	output_qty,
	bom_type,
	conversion_cost=0,
	inward_transport_cost=0,
	factory_overheads=0,
	layers=None,
	moq_percentages=None,
	precision=3,
):
	"""Calculate a per-finished-unit Sub BOM or Parent BOM cost breakdown.

	Component row quantities and amounts describe the full BOM batch. Direct
	conversion/overhead inputs and every returned custom total are per finished
	unit, so a child BOM can always be used as a unit rate by its parent.
	"""
	precision = 3 if precision in (None, "") else int(precision)
	precision = max(0, min(precision, 6))
	batch_total = round_cost(raw_materials_batch_total, precision)
	quantity = decimal_value(output_qty)
	if quantity <= 0:
		quantity = Decimal("1")
	unit_raw_total = round_cost(decimal_value(batch_total) / quantity, precision)

	result = {
		"raw_materials_batch_total": batch_total,
		"raw_materials_unit_total": unit_raw_total,
		"layers": {},
		"moq_prices": {},
	}

	if str(bom_type or "Parent BOM").strip() == "Sub BOM":
		final_cost = round_cost(decimal_value(unit_raw_total) + decimal_value(conversion_cost), precision)
		result.update(final_cost=final_cost, rollup_cost=final_cost)
		return result

	running_total = round_cost(
		decimal_value(unit_raw_total)
		+ decimal_value(inward_transport_cost)
		+ decimal_value(factory_overheads),
		precision,
	)
	for key, percentage in layers or []:
		base = running_total
		value = round_cost(decimal_value(base) * decimal_value(percentage) / Decimal("100"), precision)
		running_total = round_cost(decimal_value(base) + decimal_value(value), precision)
		result["layers"][key] = {"base": base, "value": value, "total": running_total}

	result.update(final_cost=running_total, rollup_cost=running_total)
	for key, percentage in (moq_percentages or {}).items():
		result["moq_prices"][key] = round_cost(
			decimal_value(running_total) * (Decimal("1") + decimal_value(percentage) / Decimal("100")),
			precision,
		)
	return result
