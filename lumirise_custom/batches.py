"""Batch/serial helpers for the line-aware production drivers.

ERPNext v16 refuses to post an *outbound* (or transfer) stock row for a
batch- or serial-tracked item unless the row carries the batch/serial it is
moving. Our one-click production drivers build Stock Entry rows in code and
auto-submit them — the user never sees the form — so they must attach the batch
themselves, exactly as a user would by ticking "Use Serial No / Batch Fields"
and typing the batch on the row.

`split_for_batches` FIFO-allocates the requested qty across the batches actually
sitting in the source warehouse and returns one Stock Entry item row per batch,
each tagged with ``use_serial_batch_fields = 1`` + ``batch_no``. Plain
(untracked) items pass straight through as a single row.
"""

import frappe
from frappe import _
from frappe.utils import flt


def split_for_batches(item_code, qty, s_warehouse, t_warehouse=None, extra=None):
	"""Build the Stock Entry ``items`` rows for moving ``qty`` of ``item_code``
	out of ``s_warehouse``. Untracked items → one plain row. Batch-tracked items
	→ one row per FIFO-allocated batch, tagged with the batch so the entry posts."""
	qty = flt(qty)
	base = {"item_code": item_code, "qty": qty, "s_warehouse": s_warehouse}
	if t_warehouse:
		base["t_warehouse"] = t_warehouse
	if extra:
		base.update(extra)

	has_batch, has_serial = frappe.get_cached_value(
		"Item", item_code, ["has_batch_no", "has_serial_no"])

	if not has_batch:
		if has_serial:
			frappe.throw(_("{0} is serial-tracked; serial picking is not wired into "
				"the one-click production moves yet.").format(item_code))
		return [base]

	rows = []
	for batch_no, batch_qty in allocate_batches(item_code, qty, s_warehouse):
		row = dict(base)
		row.update({"qty": batch_qty, "use_serial_batch_fields": 1, "batch_no": batch_no})
		rows.append(row)
	return rows


def allocate_batches(item_code, qty, warehouse):
	"""FIFO-allocate ``qty`` across the batches available in ``warehouse``.
	Returns a list of ``(batch_no, qty)`` tuples summing to ``qty``; throws a
	clear shortage error if the warehouse cannot cover it."""
	from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import (
		get_auto_batch_nos,
	)

	qty = flt(qty)
	available = get_auto_batch_nos(frappe._dict({
		"item_code": item_code,
		"warehouse": warehouse,
		"qty": qty,
		"based_on": "FIFO",
		# These are internal plant moves (line → store → dispatch), not customer
		# deliveries, so stock reserved against a Sales Order is still physically
		# present and movable within our own warehouses. The native Delivery Note
		# remains the document that honours the reservation.
		"ignore_reserved_stock": 1,
	}))

	allocation, remaining = [], qty
	for batch in available:
		take = min(flt(batch.get("qty")), remaining)
		if take <= 0:
			continue
		allocation.append((batch.get("batch_no"), take))
		remaining = flt(remaining - take)
		if remaining <= 0:
			break

	if remaining > 0:
		frappe.throw(_("Not enough batch stock of {0} in {1} — short by {2}. "
			"Receive the finished goods into this store first.").format(
			item_code, warehouse, remaining))
	return allocation
