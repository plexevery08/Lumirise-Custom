# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Customer PDI = pre-dispatch inspection with the customer, modelled exactly on the
# Focus / FG-stores floor process:
#
#   1. FG/Dispatch raises a request to send finished goods (a child table of FG
#      items + qty) from the Finished Goods store to the Customer PDI store.
#   2. The STORE must authorize the request. Only on authorization does stock
#      physically move FG -> PDI (a submitted Material Transfer), so the boxes
#      become visible in the PDI store. No authorization => no stock moves.
#   3. Quality inspects in the PDI store and records per-item Pass/Fail.
#   4. On completion the STORE authorizes the return: accepted boxes go back
#      PDI -> FG (dispatchable again), failed boxes go PDI -> Rejection. The
#      Customer PDI is then submitted, which opens the Delivery Note gate
#      (events.customer_pdi_gate) for a passed sign-off.
#
# The document stays in Draft (docstatus 0) for the whole operational flow and is
# only submitted at step 4, so the existing dispatch gate (docstatus 1 + sign-off
# Pass) and the task-engine on_submit handler keep working unchanged. All stock
# movements are submitted, batch-aware Stock Entries with a full audit trail; a
# cancel reverses every entry the PDI created so nothing is ever stranded.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from lumirise_custom import batches
from lumirise_custom import defaults as config

# --- Status values (single source of truth) ---------------------------------
DRAFT = "Draft"
PENDING_AUTH = "Pending Store Authorization"
AT_PDI = "At PDI - Under Inspection"
INSPECTED = "Inspection Completed"
COMPLETED = "Returned to FG - Completed"
SEND_REJECTED = "Send Rejected"
CANCELLED = "Cancelled"

# Roles allowed to authorize a store movement (issue to PDI / return to FG).
# The store login should be granted "Factory Store Manager"; System Manager is the
# admin fallback. Kept here so the gate is explicit and easy to retune.
STORE_AUTH_ROLES = {"Factory Store Manager", "System Manager"}

DEFAULT_CHECKS = [
	"Glow / Lumen",
	"Wattage / CCT",
	"Packaging & Master Box",
	"Screws & Fitment",
	"Internal Label / Print",
	"Box Serial / K-slot Count",
]


class CustomerPDI(Document):
	# ---- lifecycle ---------------------------------------------------------
	def validate(self):
		if not self.status:
			self.status = DRAFT
		if not self.inspection_date:
			self.inspection_date = frappe.utils.today()

		# Resolve operational warehouses from Operations Settings when blank, so we
		# never depend on a hard-coded, site-specific warehouse name.
		if not self.source_warehouse:
			self.source_warehouse = config.dispatch_fg_warehouse()
		if not self.pdi_warehouse:
			self.pdi_warehouse = config.pdi_warehouse()
		if not self.rejection_warehouse:
			self.rejection_warehouse = config.rejection_warehouse(required=False)

		if self.source_warehouse and self.source_warehouse == self.pdi_warehouse:
			frappe.throw(_("The Finished Goods warehouse and the Customer PDI warehouse must be different."))

		if not self.items:
			frappe.throw(_("Add at least one FG item to send for inspection."))

		for row in self.items:
			if not row.fg_item:
				frappe.throw(_("Row {0}: select an FG item.").format(row.idx))
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0} ({1}): Qty to PDI must be greater than zero.").format(row.idx, row.fg_item))
			# Show on-hand at request time only — once the flow has started the
			# number would be misleading (the sample has already moved).
			if self.status == DRAFT:
				row.available_qty = _on_hand(row.fg_item, self.source_warehouse)

		# A starter checklist for the inspector, only while still a draft.
		if self.status == DRAFT and not self.checks:
			for parameter in DEFAULT_CHECKS:
				self.append("checks", {"parameter": parameter, "result": "Accepted"})

		self._guard_locked_items()

	def _guard_locked_items(self):
		"""Once the request has left Draft, the item list + qty are frozen — only
		inspection columns (result / accepted / rejected / remarks) may change."""
		if self.is_new() or self.status == DRAFT:
			return
		before = self.get_doc_before_save()
		if not before:
			return
		old = {r.name: (r.fg_item, flt(r.qty)) for r in before.items}
		new = {r.name: (r.fg_item, flt(r.qty)) for r in self.items}
		if set(old) != set(new) or any(old[name] != new[name] for name in old):
			frappe.throw(_("Items and quantities are locked once the request is sent for "
				"authorization. Cancel and amend the Customer PDI to change them."))

	def before_submit(self):
		# Submission is the LAST step and only ever happens via authorize_return.
		# Block a stray native Submit so the flow cannot be short-circuited.
		if self.status != COMPLETED:
			frappe.throw(_("Use the <b>Authorize Return to FG</b> action to complete and "
				"submit this Customer PDI — it cannot be submitted directly."))
		if not self.customer_signoff:
			frappe.throw(_("Customer Sign-off is not set. Complete the inspection first."))

	def on_cancel(self):
		# Reverse every stock movement this PDI posted, newest first, so nothing is
		# left stranded in the PDI store. Frappe blocks a reversal that would create
		# negative stock (e.g. the FG was already dispatched), surfacing a clear error.
		self.db_set("status", CANCELLED)
		for field in ("rejection_stock_entry", "return_stock_entry", "send_stock_entry"):
			_cancel_stock_entry(self.get(field))


# --- shared helpers ---------------------------------------------------------
def _on_hand(item_code, warehouse):
	if not (item_code and warehouse):
		return 0.0
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))


def _require_store_authority():
	if not (STORE_AUTH_ROLES & set(frappe.get_roles())):
		frappe.throw(
			_("Only the Store (role <b>Factory Store Manager</b>) can authorize this "
			  "movement. Ask the store in-charge to authorize."),
			frappe.PermissionError,
			title=_("Store Authorization Required"),
		)


def _load(docname):
	"""Always operate on a fresh copy from the database, never on client state."""
	return frappe.get_doc("Customer PDI", docname)


def _post_transfer(doc, from_wh, to_wh, lines, narration):
	"""Post ONE submitted Material Transfer for the given (item_code, qty) lines
	between two warehouses. Batch-tracked items are split per batch so the entry
	posts. Returns the Stock Entry name, or None if there is nothing to move."""
	rows = []
	for item_code, qty in lines:
		if flt(qty) <= 0:
			continue
		rows.extend(batches.split_for_batches(item_code, flt(qty), from_wh, to_wh))
	if not rows:
		return None
	se = frappe.get_doc({
		"doctype": "Stock Entry",
		"stock_entry_type": "Material Transfer",
		"company": config.get_company(doc),
		"from_warehouse": from_wh,
		"to_warehouse": to_wh,
		"custom_narration": narration,
		"items": rows,
	})
	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


def _cancel_stock_entry(name):
	if not name:
		return
	if not frappe.db.exists("Stock Entry", name):
		return
	se = frappe.get_doc("Stock Entry", name)
	if se.docstatus == 1:
		se.flags.ignore_permissions = True
		se.cancel()


def _check_availability(doc):
	"""Raise a clear, per-item error if the Finished Goods store cannot cover the
	requested qty. Aggregated by item in case an item appears on several rows."""
	wanted = {}
	for row in doc.items:
		wanted[row.fg_item] = wanted.get(row.fg_item, 0.0) + flt(row.qty)
	for item_code, qty in wanted.items():
		on_hand = _on_hand(item_code, doc.source_warehouse)
		if on_hand + 0.001 < qty:
			frappe.throw(_("Only {0} of {1} in {2} — cannot send {3} to the Customer PDI "
				"store. Move finished goods to the FG store first.").format(
				on_hand, item_code, doc.source_warehouse, qty))


def _notify(**kwargs):
	"""Fail-safe task creation — never blocks the flow if the task engine errors."""
	try:
		from lumirise_custom.task_engine import create_task

		create_task(**kwargs)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Customer PDI task")


# --- flow transitions (called from the form buttons) ------------------------
@frappe.whitelist()
def send_for_authorization(docname):
	"""FG/Dispatch raises the request. No stock moves yet — it goes to the store
	for authorization."""
	frappe.has_permission("Customer PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.docstatus != 0 or doc.status != DRAFT:
		frappe.throw(_("Only a Draft Customer PDI can be sent for authorization."))

	doc.requested_by = frappe.session.user
	doc.requested_on = now_datetime()
	doc.status = PENDING_AUTH
	doc.save(ignore_permissions=True)

	_notify(
		title=f"Authorize Customer PDI issue — {doc.name}",
		department="FG Stores - Dispatch",
		task_type="Handoff",
		priority="High",
		reference_doctype="Customer PDI",
		reference_name=doc.name,
		description=(
			f"FG/Dispatch raised {doc.name} to send {len(doc.items)} item(s) to the "
			f"Customer PDI store ({doc.pdi_warehouse}). Verify the request and authorize "
			f"the issue (FG -> PDI) so the boxes move to the PDI store."
		),
		source_event="cpdi_pending_auth",
	)
	return {"status": doc.status}


@frappe.whitelist()
def authorize_send(docname):
	"""STORE authorizes the request: post the FG -> PDI transfer so the boxes
	become available in the Customer PDI store, then hand off to Quality."""
	_require_store_authority()
	frappe.has_permission("Customer PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.docstatus != 0 or doc.status != PENDING_AUTH:
		frappe.throw(_("This Customer PDI is not pending store authorization."))
	if doc.send_stock_entry:
		frappe.throw(_("The issue has already been authorized ({0}).").format(doc.send_stock_entry))
	if not doc.pdi_warehouse:
		frappe.throw(_("Set the Customer PDI Warehouse before authorizing."))

	_check_availability(doc)
	se = _post_transfer(
		doc, doc.source_warehouse, doc.pdi_warehouse,
		[(r.fg_item, r.qty) for r in doc.items],
		f"Customer PDI {doc.name}: issued to PDI store for inspection",
	)

	doc.send_stock_entry = se
	doc.sent_authorized_by = frappe.session.user
	doc.sent_authorized_on = now_datetime()
	doc.status = AT_PDI
	doc.save(ignore_permissions=True)

	_notify(
		title=f"Inspect Customer PDI — {doc.name}",
		department="Quality - PDI/IQC",
		task_type="Handoff",
		priority="High",
		reference_doctype="Customer PDI",
		reference_name=doc.name,
		description=(
			f"Stock for {doc.name} is in the Customer PDI store ({doc.pdi_warehouse}). "
			f"Run the inspection, record per-item accepted / rejected qty, then Complete "
			f"Inspection."
		),
		source_event="cpdi_at_pdi",
	)
	return {"status": doc.status, "stock_entry": se}


@frappe.whitelist()
def reject_send(docname, reason=None):
	"""STORE declines the request before any stock moves."""
	_require_store_authority()
	frappe.has_permission("Customer PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.docstatus != 0 or doc.status != PENDING_AUTH:
		frappe.throw(_("Only a request pending store authorization can be rejected."))

	doc.status = SEND_REJECTED
	doc.authorization_remarks = reason or "Rejected by store."
	doc.save(ignore_permissions=True)

	_notify(
		title=f"Customer PDI issue rejected — {doc.name}",
		department="FG Stores - Dispatch",
		task_type="Handoff",
		priority="Medium",
		reference_doctype="Customer PDI",
		reference_name=doc.name,
		description=f"The store rejected the PDI issue request {doc.name}. Reason: {reason or '—'}.",
		source_event="cpdi_send_rejected",
	)
	return {"status": doc.status}


@frappe.whitelist()
def complete_inspection(docname):
	"""Quality finishes the inspection. Reads the per-item accepted/rejected qty
	the inspector entered, derives each row's result + the overall sign-off, and
	hands off to the store to authorize the return."""
	frappe.has_permission("Customer PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.docstatus != 0 or doc.status != AT_PDI:
		frappe.throw(_("This Customer PDI is not under inspection."))

	total_rejected = 0.0
	for row in doc.items:
		qty = flt(row.qty)
		acc, rej = flt(row.accepted_qty), flt(row.rejected_qty)
		if acc == 0 and rej == 0:
			acc, rej = qty, 0.0  # untouched row => full pass
		elif acc == 0:
			acc = qty - rej
		elif rej == 0 and acc < qty:
			rej = qty - acc
		if acc < 0 or rej < 0:
			frappe.throw(_("Row {0} ({1}): accepted and rejected qty cannot be negative.").format(row.idx, row.fg_item))
		if abs((acc + rej) - qty) > 0.001:
			frappe.throw(_("Row {0} ({1}): accepted ({2}) + rejected ({3}) must equal the qty "
				"sent ({4}).").format(row.idx, row.fg_item, acc, rej, qty))
		row.accepted_qty = acc
		row.rejected_qty = rej
		row.result = "Fail" if rej > 0 else "Pass"
		total_rejected += rej

	checks_failed = any((c.result == "Rejected") for c in doc.checks)
	doc.customer_signoff = "Fail" if (total_rejected > 0 or checks_failed) else "Pass"
	doc.status = INSPECTED
	doc.save(ignore_permissions=True)

	_notify(
		title=f"Authorize Customer PDI return — {doc.name}",
		department="FG Stores - Dispatch",
		task_type="Handoff",
		priority="High",
		reference_doctype="Customer PDI",
		reference_name=doc.name,
		description=(
			f"Inspection of {doc.name} is complete (sign-off: {doc.customer_signoff}). "
			f"Authorize the return so accepted boxes go back to the FG store"
			+ (" and rejected boxes route to the Rejection store." if total_rejected else ".")
		),
		source_event="cpdi_inspected",
	)
	return {"status": doc.status, "customer_signoff": doc.customer_signoff}


@frappe.whitelist()
def authorize_return(docname):
	"""STORE authorizes the return. Accepted boxes move PDI -> FG (dispatchable
	again); rejected boxes move PDI -> Rejection. The Customer PDI is then
	submitted, opening the dispatch gate for a passed sign-off."""
	_require_store_authority()
	frappe.has_permission("Customer PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.docstatus != 0 or doc.status != INSPECTED:
		frappe.throw(_("This Customer PDI inspection is not completed yet."))
	if doc.return_stock_entry or doc.rejection_stock_entry:
		frappe.throw(_("The return has already been authorized for this Customer PDI."))

	accepted = [(r.fg_item, r.accepted_qty) for r in doc.items if flt(r.accepted_qty) > 0]
	rejected = [(r.fg_item, r.rejected_qty) for r in doc.items if flt(r.rejected_qty) > 0]

	if rejected and not doc.rejection_warehouse:
		frappe.throw(_("Set a Rejection Warehouse — some inspected boxes failed and must "
			"be routed out of dispatchable stock."))

	doc.return_stock_entry = _post_transfer(
		doc, doc.pdi_warehouse, doc.source_warehouse, accepted,
		f"Customer PDI {doc.name}: passed boxes returned to FG store",
	)
	if rejected:
		doc.rejection_stock_entry = _post_transfer(
			doc, doc.pdi_warehouse, doc.rejection_warehouse, rejected,
			f"Customer PDI {doc.name}: failed boxes moved to Rejection store",
		)

	doc.return_authorized_by = frappe.session.user
	doc.return_authorized_on = now_datetime()
	doc.status = COMPLETED
	doc.flags.ignore_permissions = True
	doc.submit()  # before_submit passes (status COMPLETED); on_submit raises Pass/Fail tasks
	return {
		"status": doc.status,
		"customer_signoff": doc.customer_signoff,
		"return_stock_entry": doc.return_stock_entry,
		"rejection_stock_entry": doc.rejection_stock_entry,
	}


@frappe.whitelist()
def reopen_as_draft(docname):
	"""Put a store-rejected request back to Draft so FG can revise and re-raise it."""
	frappe.has_permission("Customer PDI", "write", docname, throw=True)
	doc = _load(docname)
	if doc.docstatus != 0 or doc.status != SEND_REJECTED:
		frappe.throw(_("Only a store-rejected request can be reopened."))
	doc.status = DRAFT
	doc.authorization_remarks = None
	doc.requested_by = None
	doc.requested_on = None
	doc.save(ignore_permissions=True)
	return {"status": doc.status}
