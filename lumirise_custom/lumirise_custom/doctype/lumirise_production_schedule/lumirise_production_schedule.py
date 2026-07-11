# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Lumirise Production Schedule = the PPC monthly/weekly/daily plan (2026-07-08 call).
# The planner DATES each FG slice manually (client answer #3 — no auto-scheduler in
# v1); on validate the system computes, per line, advisory-only decorations:
#   - lines_needed  = slice_qty / Item.lr_cph      (their sheet's "LINES" column)
#   - material_status: makeable-now vs incoming, from the shared MRP helpers
#   - warnings: capacity (lines needed on a date > active lines) + delivery-date slip
# Nothing here blocks a save/submit — the algorithm advises, the human decides.

import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate

from lumirise_custom import defaults as config
from lumirise_custom.lumirise_custom.doctype.material_planning.material_planning import (
	_stock,
	_open_po,
	_pending_pdi,
	_in_transit,
)


class LumiriseProductionSchedule(Document):
	def validate(self):
		active_lines = len(config.production_lines(active_only=True))

		# lines-needed + material status per row; tally lines-needed per calendar date
		per_date = {}
		for ln in self.schedule_lines:
			cph = flt(frappe.db.get_value("Item", ln.fg_item, "lr_cph")) if ln.fg_item else 0
			ln.lines_needed = (flt(ln.slice_qty) / cph) if cph else 0
			ln.material_status = _material_status(ln.fg_item, flt(ln.slice_qty)) if ln.fg_item else ""
			if ln.scheduled_date:
				per_date[ln.scheduled_date] = per_date.get(ln.scheduled_date, 0) + flt(ln.lines_needed)

		# warnings pass (needs the full per_date tally first)
		for ln in self.schedule_lines:
			warns = []
			if ln.fg_item and not flt(frappe.db.get_value("Item", ln.fg_item, "lr_cph")):
				warns.append("No CPH on the FG item — lines-needed can't be computed.")
			if ln.scheduled_date and active_lines and per_date.get(ln.scheduled_date, 0) > active_lines:
				warns.append(
					f"Capacity: {per_date[ln.scheduled_date]:.1f} lines needed on {ln.scheduled_date} "
					f"(only {active_lines} active)."
				)
			if ln.sales_order and ln.scheduled_date:
				deliv = frappe.db.get_value("Sales Order", ln.sales_order, "delivery_date")
				if deliv and getdate(ln.scheduled_date) > getdate(deliv):
					warns.append(f"Delivery: scheduled {ln.scheduled_date} is after the SO delivery date {deliv}.")
			ln.warnings = " ".join(warns)


def _material_status(fg_item, qty):
	"""How much of `qty` can be built now from RM on hand, and whether the incoming
	pipeline (open PO + Vendor PDI + in-transit) closes the gap. Reuses the single-
	source MRP helpers so this never disagrees with Material Planning."""
	bom = frappe.db.get_value("Item", fg_item, "default_bom")
	if not bom:
		return "No BOM on FG"
	bom_doc = frappe.get_doc("BOM", bom)
	per = flt(bom_doc.quantity) or 1
	rm_wh = config.rm_warehouse()
	worst = None  # (makeable_now, makeable_incl_incoming, component)
	for bi in bom_doc.items:
		need_per_unit = flt(bi.qty) / per
		if need_per_unit <= 0:
			continue
		avail = _stock(bi.item_code, rm_wh)
		incoming = _open_po(bi.item_code) + _pending_pdi(bi.item_code) + _in_transit(bi.item_code)
		makeable = avail / need_per_unit
		makeable_inc = (avail + incoming) / need_per_unit
		if worst is None or makeable < worst[0]:
			worst = (makeable, makeable_inc, bi.item_code)
	if worst is None:
		return "No components"
	makeable, makeable_inc, comp = worst
	if makeable >= qty:
		return f"RM enough (~{int(makeable)} makeable now)"
	if makeable_inc >= qty:
		return f"Short {int(qty - makeable)} now — incoming covers it ({comp})"
	return f"SHORT: only ~{int(makeable_inc)} makeable incl. in-transit ({comp})"


@frappe.whitelist()
def get_suggested_order(sales_orders):
	"""Read-only helper: the priority/urgent% ordering the planner can consult — all
	URGENT slices first (by priority), then all NORMAL slices (by priority). Writes
	nothing; the planner still dates rows by hand (answer #3). 1 = highest priority."""
	import json

	if isinstance(sales_orders, str):
		sales_orders = json.loads(sales_orders)

	urgent, normal = [], []
	for so in sales_orders:
		so_doc = frappe.get_doc("Sales Order", so)
		priority = int(so_doc.get("lr_priority") or 999999)
		urgent_pct = flt(so_doc.get("lr_urgent_percent"))
		for it in so_doc.items:
			u_qty = flt(it.qty) * urgent_pct / 100.0
			n_qty = flt(it.qty) - u_qty
			if u_qty > 0:
				urgent.append({"sales_order": so, "fg_item": it.item_code, "qty": u_qty,
							   "urgent": 1, "priority": priority})
			if n_qty > 0:
				normal.append({"sales_order": so, "fg_item": it.item_code, "qty": n_qty,
							   "urgent": 0, "priority": priority})
	urgent.sort(key=lambda r: r["priority"])
	normal.sort(key=lambda r: r["priority"])
	return urgent + normal


def _assign_jobcard(jc_name, user):
	"""ToDo + notification to the line supervisor (mirrors task_engine._assign, for a
	Job Card). Fail-safe — a missing/disabled user just means an unassigned card."""
	if not user:
		return
	try:
		from frappe.desk.form.assign_to import add as assign_add

		assign_add({
			"assign_to": [user],
			"doctype": "Lumirise Job Card",
			"name": jc_name,
			"description": f"Daily production target — {jc_name}",
			"notify": 1,
		})
	except frappe.exceptions.DuplicateEntryError:
		pass
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Production Schedule: Job Card assign failed")


@frappe.whitelist()
def release_day(schedule_name, production_date):
	"""Create a Lumirise Job Card per schedule line dated `production_date`, assigned to
	that line's supervisor. Deduped on (schedule_ref, line, date, fg) so re-releasing a
	day is safe. plan_qty + the initial target = the scheduled slice (the supervisor's
	Carry-Fwd + New-RM later overrides target to the material-driven number)."""
	sched = frappe.get_doc("Lumirise Production Schedule", schedule_name)
	if sched.docstatus != 1:
		frappe.throw("Submit the schedule before releasing a day.")
	target = getdate(production_date)
	created = []
	for ln in sched.schedule_lines:
		if not ln.scheduled_date or getdate(ln.scheduled_date) != target:
			continue
		# Dedup per schedule LINE (row name) — re-releasing a day is safe and no slice is
		# ever collapsed/lost, even if two lines share the same line/date/product.
		if frappe.db.exists("Lumirise Job Card", {"schedule_line": ln.name, "docstatus": ["<", 2]}):
			continue
		customer = frappe.db.get_value("Sales Order", ln.sales_order, "customer") if ln.sales_order else None
		jc = frappe.get_doc({
			"doctype": "Lumirise Job Card",
			"production_line": ln.production_line,
			"production_date": ln.scheduled_date,
			"fg_item": ln.fg_item,
			"work_order": ln.work_order or None,
			"sales_order": ln.sales_order,
			"customer": customer,
			"schedule_ref": schedule_name,
			"schedule_line": ln.name,
			"plan_qty": flt(ln.slice_qty),
			"target_qty": flt(ln.slice_qty),
		})
		jc.insert(ignore_permissions=True)
		created.append(jc.name)
		sup = frappe.db.get_value("Lumirise Production Line", ln.production_line, "supervisor_user")
		_assign_jobcard(jc.name, sup)
	if created and sched.release_status != "Released":
		sched.db_set("release_status", "Released")
	frappe.db.commit()
	frappe.msgprint(f"Released {len(created)} Job Card(s) for {target}.", indicator="green", alert=True)
	return created


@frappe.whitelist()
def roll_backlog(schedule_name, from_date, to_date):
	"""Roll each Missed Job Card from `from_date` into a backlog Job Card on `to_date`
	(qty = the shortfall), assigned to the same line supervisor. Deduped on backlog_of."""
	missed = frappe.get_all(
		"Lumirise Job Card",
		filters={
			"schedule_ref": schedule_name,
			"production_date": getdate(from_date),
			"status": "Missed",
			"docstatus": 1,
		},
		fields=["name", "production_line", "fg_item", "sales_order", "customer", "target_qty", "produced_qty"],
	)
	created = []
	for m in missed:
		shortfall = flt(m.target_qty) - flt(m.produced_qty)
		if shortfall <= 0:
			continue
		if frappe.db.exists("Lumirise Job Card", {"backlog_of": m.name, "docstatus": ["<", 2]}):
			continue
		jc = frappe.get_doc({
			"doctype": "Lumirise Job Card",
			"production_line": m.production_line,
			"production_date": getdate(to_date),
			"fg_item": m.fg_item,
			"sales_order": m.sales_order,
			"customer": m.customer,
			"schedule_ref": schedule_name,
			"backlog_of": m.name,
			"plan_qty": shortfall,
			"target_qty": shortfall,
		})
		jc.insert(ignore_permissions=True)
		created.append(jc.name)
		sup = frappe.db.get_value("Lumirise Production Line", m.production_line, "supervisor_user")
		_assign_jobcard(jc.name, sup)
	frappe.db.commit()
	frappe.msgprint(f"Rolled {len(created)} backlog Job Card(s) to {getdate(to_date)}.", indicator="orange", alert=True)
	return created
