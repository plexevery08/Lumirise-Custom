"""Authoritative, side-effect-free stock quantity contracts for Phase 0."""

from __future__ import annotations

from typing import TypedDict

from frappe.utils import flt


class IncomingBuckets(TypedDict):
	pending_order: float
	pending_pdi: float
	in_transit: float
	pending_iqc: float
	incoming: float
	overlap_qty: float


class Availability(TypedDict):
	on_hand: float
	unusable_on_hand: float
	usable_on_hand: float
	committed: float
	reserved: float
	raw_free: float
	free_now: float
	incoming: float
	additional_demand: float
	projected_raw: float
	projected_surplus: float
	shortfall: float


# The source map is documentation in executable form.  Reports may aggregate
# multiple warehouses, but they must preserve these meanings.
QUANTITY_SOURCES = {
	"on_hand": ("Bin.actual_qty",),
	"committed": (
		"Bin.reserved_qty_for_production",
		"Bin.reserved_qty_for_sub_contract",
		"Bin.reserved_qty_for_production_plan",
	),
	"reserved": ("Bin.reserved_qty",),
	"unusable_on_hand": ("configured rejection/quarantine warehouse balances",),
	"incoming": ("pending_order", "pending_pdi", "in_transit", "pending_iqc"),
}


def _qty(value) -> float:
	return flt(value or 0)


def incoming_buckets(
	open_order_qty=0,
	*,
	pending_pdi=0,
	in_transit=0,
	pending_iqc=0,
) -> IncomingBuckets:
	"""Turn an inclusive open-PO total into mutually exclusive pre-GRN stages.

	``open_order_qty`` includes quantities that have moved into the three later
	stages.  Only the residual remains in ``pending_order``.  Posted receipts are
	not an argument and therefore can never remain in Incoming.
	"""
	open_order = max(_qty(open_order_qty), 0)
	stages = {
		"pending_pdi": max(_qty(pending_pdi), 0),
		"in_transit": max(_qty(in_transit), 0),
		"pending_iqc": max(_qty(pending_iqc), 0),
	}
	stage_total = sum(stages.values())
	pending_order = max(open_order - stage_total, 0)
	return {
		"pending_order": pending_order,
		**stages,
		"incoming": pending_order + stage_total,
		"overlap_qty": max(stage_total - open_order, 0),
	}


def availability(
	*,
	on_hand=0,
	unusable_on_hand=0,
	committed=0,
	reserved=0,
	incoming=0,
	additional_demand=0,
) -> Availability:
	"""Calculate availability without hiding deficits or double-subtracting demand."""
	on_hand_qty = _qty(on_hand)
	unusable_qty = max(_qty(unusable_on_hand), 0)
	committed_qty = max(_qty(committed), 0)
	reserved_qty = max(_qty(reserved), 0)
	incoming_qty = max(_qty(incoming), 0)
	additional_demand_qty = max(_qty(additional_demand), 0)

	usable_on_hand = on_hand_qty - unusable_qty
	raw_free = usable_on_hand - committed_qty - reserved_qty
	projected_raw = raw_free + incoming_qty - additional_demand_qty

	return {
		"on_hand": on_hand_qty,
		"unusable_on_hand": unusable_qty,
		"usable_on_hand": usable_on_hand,
		"committed": committed_qty,
		"reserved": reserved_qty,
		"raw_free": raw_free,
		"free_now": max(raw_free, 0),
		"incoming": incoming_qty,
		"additional_demand": additional_demand_qty,
		"projected_raw": projected_raw,
		"projected_surplus": max(projected_raw, 0),
		"shortfall": max(-projected_raw, 0),
	}

