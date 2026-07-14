# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Lumirise Production Schedule = the PPC monthly/weekly/daily plan (2026-07-08 call).
# "Get Sales Orders" (fetch_sales_orders) auto-populates every row from open Sales
# Orders — the native-Production-Plan pattern: SO, FG item, pending qty, Category,
# CPH, LINES, delivery date, priority/urgent, and an auto material/container remark.
# The planner then only sets the Production Date + Line manually (client answer #3 —
# no auto-scheduler in v1). On validate the system (re)computes advisory-only:
#   - cph / lines_needed = slice_qty / Item.lr_cph  (their sheet's "LINES" column)
#   - category (FG Item Group), delivery_date, remark (material/container hint)
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
			ln.cph = cph
			ln.lines_needed = (flt(ln.slice_qty) / cph) if cph else 0
			ln.material_status = _material_status(ln.fg_item, flt(ln.slice_qty)) if ln.fg_item else ""
			# Auto-decorate the "July Sales" columns (all editable afterwards).
			if ln.fg_item and not ln.category:
				ln.category = frappe.db.get_value("Item", ln.fg_item, "item_group")
			if ln.sales_order and not ln.delivery_date:
				ln.delivery_date = frappe.db.get_value("Sales Order", ln.sales_order, "delivery_date")
			if not (ln.remark or "").strip():
				ln.remark = _material_remark(ln.fg_item, flt(ln.slice_qty)) if ln.fg_item else ""
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


def _material_remark(fg_item, qty):
	"""Short auto note for the REMARK column — surfaces a material/container-release
	dependency the way the client's sheet does ('NEED CONTAINER RELEASE DATE'), so the
	planner sees the blocker without free-typing it. Blank when RM is enough now."""
	status = _material_status(fg_item, flt(qty))
	if status.startswith("RM enough") or status in ("No components", ""):
		return ""
	if status.startswith("Short") and "incoming covers" in status:
		return "MATERIAL INCOMING — check container-release date"
	if status.startswith("SHORT"):
		return "NEEDS MATERIAL / CONTAINER RELEASE"
	if status == "No BOM on FG":
		return "No BOM on FG — cannot check material"
	return ""


@frappe.whitelist()
def fetch_sales_orders(schedule_name, from_date=None, to_date=None, customer=None, only_pending=1):
	"""Native-Production-Plan-style fetch: pull every open Sales Order FG line and
	populate the schedule automatically (SO, item, pending qty, category, CPH, LINES,
	delivery date, priority/urgent, and an auto material/container remark). The planner
	then only sets the Production Date + Line (client answer #3 — manual dating in v1).

	Dedupes on (sales_order, fg_item) so re-fetching is safe. Returns the count added.
	Rate-less/advisory — never blocks; a bad row is skipped, not thrown."""
	sched = frappe.get_doc("Lumirise Production Schedule", schedule_name)
	if sched.docstatus != 0:
		frappe.throw("Fetch Sales Orders only on a draft schedule.")

	only_pending = int(only_pending or 0)
	existing = {(ln.sales_order, ln.fg_item) for ln in sched.schedule_lines}

	so_filters = {"docstatus": 1, "status": ["not in", ["Closed", "Completed"]]}
	if customer:
		so_filters["customer"] = customer
	if from_date:
		so_filters["delivery_date"] = [">=", from_date]
	if from_date and to_date:
		so_filters["delivery_date"] = ["between", [from_date, to_date]]
	elif to_date:
		so_filters["delivery_date"] = ["<=", to_date]

	sales_orders = frappe.get_all("Sales Order", filters=so_filters, pluck="name")
	added = 0
	for so in sales_orders:
		so_doc = frappe.get_doc("Sales Order", so)
		priority = int(so_doc.get("lr_priority") or 0)
		urgent = 1 if flt(so_doc.get("lr_urgent_percent")) > 0 else 0
		for it in so_doc.items:
			pending = flt(it.qty) - flt(it.delivered_qty)
			if only_pending and pending <= 0:
				continue
			qty = pending if only_pending else flt(it.qty)
			if (so, it.item_code) in existing:
				continue
			cph = flt(frappe.db.get_value("Item", it.item_code, "lr_cph"))
			sched.append("schedule_lines", {
				"sales_order": so,
				"fg_item": it.item_code,
				"fg_item_name": it.item_name,
				"category": frappe.db.get_value("Item", it.item_code, "item_group"),
				"slice_qty": qty,
				"cph": cph,
				"lines_needed": (qty / cph) if cph else 0,
				"delivery_date": it.delivery_date or so_doc.delivery_date,
				"priority": priority,
				"urgent_flag": urgent,
				"remark": _material_remark(it.item_code, qty),
				"material_status": _material_status(it.item_code, qty),
			})
			existing.add((so, it.item_code))
			added += 1

	if added:
		sched.save()
	return {"added": added, "sales_orders": len(sales_orders)}


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
		_assign_jobcard(jc.name, config.line_supervisor(ln.production_line))
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
		_assign_jobcard(jc.name, config.line_supervisor(m.production_line))
	frappe.db.commit()
	frappe.msgprint(f"Rolled {len(created)} backlog Job Card(s) to {getdate(to_date)}.", indicator="orange", alert=True)
	return created
