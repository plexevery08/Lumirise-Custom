import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from lumirise_custom.pricing_engine import (
	calculate_approval_price,
	generate_rows,
	get_master_box_caselots,
	get_settings,
	moq_for_quantity,
)

APPROVER_ROLES = ("Sales Approver", "System Manager")


class PriceSheet(Document):
	def validate(self):
		self.set_valid_till()
		if self.docstatus == 0:
			self.sync_configuration_queue()
			self.build_rows()
		self.apply_listening()

	def set_valid_till(self):
		settings = get_settings()
		self.valid_till = add_days(
			self.transaction_date or nowdate(), settings.approval_window_days
		)

	def build_rows(self):
		"""Regenerate rows from the current configuration on every draft save —
		rows are always consistent with the config, never hand-edited."""
		if not self.configurations and not self.products:
			frappe.throw(_("Add at least one product group in the Quotation Creator"))
		if not self.configurations:
			if self.payment_type != "Credit":
				self.credit_term = None
				self.credit_days = 0
				self.credit_percentage = 0
			if self.delivery_type != "Transport":
				self.transport_type = None
				self.transport_zone = None

		self.set("rows", [])
		for row in generate_rows(self):
			self.append("rows", row)

		if not self.rows:
			frappe.throw(
				_("No price rows could be generated — check that pricing masters "
				  "(or costed Parent BOMs) exist for the selected products")
			)

	def sync_configuration_queue(self):
		"""Keep the queue normalised and the legacy Products field in sync.

		Products remains populated for reports and historical compatibility, while
		the queue is the commercial source of truth for newly created sheets.
		"""
		if not self.configurations:
			return

		items = []
		for index, config in enumerate(self.configurations, start=1):
			config.configuration_group = config.configuration_group or _("Group {0}").format(index)
			config.delivery_type = config.delivery_type or "Ex-Factory"
			config.payment_type = config.payment_type or "Advance"
			config.mono_box_mode = "All Priced Finishes"
			if config.item and config.item not in items:
				items.append(config.item)

			if config.master_box_finish:
				config.master_box_caselots = ",".join(
					str(value)
					for value in get_master_box_caselots(config.item, config.master_box_finish)
				)
			else:
				config.master_box_caselots = None

			if config.delivery_type != "Transport":
				config.transport_type = None
				config.transport_zone = None
			if config.payment_type != "Credit":
				config.credit_days = 0

		self.set("products", [])
		for item in items:
			self.append("products", {"item": item})

	def apply_listening(self):
		"""Customer-facing total = total uplifted by the hidden listening %."""
		factor = 1 + max(flt(self.listening_percentage), 0) / 100.0
		for row in self.rows:
			row.final_total = flt(flt(row.total) * factor, 3) if row.total else row.total

	def before_submit(self):
		self.status = "Pending Approval"

	def on_cancel(self):
		self.db_set("status", "Rejected")

	# ------------------------------------------------------------------
	# Approval (port of the platform's approve_price_sheet_with_report RPC)
	# ------------------------------------------------------------------

	def check_approver(self):
		self.check_permission("write")
		frappe.only_for(APPROVER_ROLES)

	def check_window(self):
		if self.status != "Pending Approval":
			frappe.throw(_("Only pending price sheets can be approved or rejected"))
		if getdate(nowdate()) > getdate(self.valid_till):
			self.db_set("status", "Expired")
			frappe.throw(_("This price sheet's approval window has expired"))

	@frappe.whitelist()
	def populate_approval_items(self):
		"""Prefill one approval line per queued configuration.

		Like the original app, approval starts from No Mono Box / No Master Box /
		No Transport / Advance. The approver makes the final commercial choices.
		"""
		self.check_approver()
		self.check_window()
		if self.approval_items:
			return
		settings = get_settings()
		configs = self.configurations or [
			frappe._dict(configuration_group="Legacy", item=product.item)
			for product in self.products
		]
		for config in configs:
			self.append(
				"approval_items",
				{
					"configuration_group": config.configuration_group,
					"item": config.item,
					"give_to_customer": 1,
					"customer_agreed_qty": settings.min_agreed_qty,
					"mono_box_finish": None,
					"master_box_finish": None,
					"master_box_caselot": None,
					"transport_mode": "No Transport",
					"transport_type": None,
					"transport_zone": None,
					"credit_days": 0,
					"listening_percentage": self.listening_percentage,
				},
			)
		self.save()
		return len(self.approval_items)

	def compute_approval_lines(self, for_preview=False):
		"""Server-side recompute of every selected line — client values are
		never trusted for calculated prices (the platform recomputed in the
		RPC the same way).

		for_preview=True is the "Calculate Prices" action: it computes the SYSTEM
		price (base + calculated) without demanding a customer price first, and
		defaults a blank customer price to the calculated price so the approver has a
		starting figure to accept or negotiate. Approval (for_preview=False) still
		requires a customer price."""
		settings = get_settings()
		for line in self.approval_items:
			if not line.give_to_customer:
				line.selected_moq = None
				line.base_price = None
				line.calculated_price = None
				line.listening_amount = None
				line.variance = None
				continue

			quantity = flt(line.customer_agreed_qty)
			if quantity <= 0:
				frappe.throw(_("Row {0} ({1}): agreed quantity must be greater than zero").format(
					line.idx, line.item
				))
			if quantity < settings.min_agreed_qty:
				if not line.is_sample_or_exception:
					frappe.throw(
						_("Row {0} ({1}): quantity below {2} requires Sample / MOQ Exception").format(
							line.idx, line.item, settings.min_agreed_qty
						)
					)
				if not (line.exception_reason or "").strip():
					frappe.throw(
						_("Row {0} ({1}): enter the sample / MOQ exception reason").format(
							line.idx, line.item
						)
					)
			if flt(line.customer_price) <= 0 and not for_preview:
				frappe.throw(
					_("Row {0} ({1}): customer price must be greater than zero").format(
						line.idx, line.item
					)
				)

			line.selected_moq = (
				moq_for_quantity(line.customer_agreed_qty) or settings.min_agreed_qty
			)
			breakdown = calculate_approval_price(
				item=line.item,
				moq=line.selected_moq,
				mono_box_finish=line.mono_box_finish,
				master_box_finish=line.master_box_finish,
				master_box_caselot=line.master_box_caselot,
				transport_mode=line.transport_mode,
				transport_type=line.transport_type,
				transport_zone=line.transport_zone,
				credit_days=line.credit_days,
			)
			line.base_price = breakdown.base_price
			line.mono_box_price = breakdown.mono_box_price
			line.master_box_price = breakdown.master_box_price
			line.transport_price = breakdown.transport_price
			line.credit_price = breakdown.credit_price
			line.calculated_price = breakdown.calculated_price
			line.listening_amount = flt(
				flt(breakdown.calculated_price) * flt(line.listening_percentage) / 100.0, 3
			)
			# Preview seeds a blank customer price with the system price (calculated +
			# listening uplift) so the approver has a figure to accept or negotiate.
			if for_preview and not flt(line.customer_price):
				line.customer_price = flt(
					flt(breakdown.calculated_price) + flt(line.listening_amount), 3
				)
			line.variance = flt(
				flt(line.customer_price)
				- (flt(breakdown.calculated_price) + flt(line.listening_amount)),
				3,
			)

	@frappe.whitelist()
	def preview_prices(self):
		"""'Calculate Prices' action — fill base/calculated/variance for every line
		without approving or creating a Quotation. Lets the approver see the system
		price (and a defaulted customer price) before committing."""
		self.check_approver()
		self.check_window()
		self.compute_approval_lines(for_preview=True)
		self.save()
		return len(self.approval_items)

	@frappe.whitelist()
	def approve(self):
		"""Validate, recompute, save the approval report, create the Quotation,
		and flip to Approved — one server-side transaction."""
		self.check_approver()
		if self.status == "Approved":
			if self.quotation and frappe.db.exists("Quotation", self.quotation):
				return self.quotation
			frappe.throw(
				_("This Price Sheet is approved but its Quotation link is missing. Repair the link before retrying.")
			)
		self.check_window()
		selected = [l for l in (self.approval_items or []) if l.give_to_customer]
		if not selected:
			frappe.throw(_("Add at least one approval line marked Give To Customer"))

		self.compute_approval_lines()
		self.save()

		quotation = self.make_quotation(selected)
		self.db_set(
			{
				"status": "Approved",
				"approved_by": frappe.session.user,
				"approved_at": now_datetime(),
				"quotation": quotation.name,
			}
		)
		return quotation.name

	@frappe.whitelist()
	def reject(self, remarks=None):
		self.check_approver()
		self.check_window()
		self.db_set("status", "Rejected")
		if remarks:
			self.db_set("rejection_remarks", remarks)
		return self.status

	def make_quotation(self, lines):
		"""Approved price sheet becomes a real ERPNext Quotation at the
		negotiated customer price. Traceability uses read-only Data fields, not
		Link fields, so it does not create circular deletion dependencies.

		The Price Sheet IS the pricing authority — so the Quotation must NOT let
		ERPNext's own Item Price / Pricing Rules re-price the line (that once turned
		a negotiated 150 into a demo Pricing-Rule's 570). We set ignore_pricing_rule
		and pin price_list_rate = the negotiated rate so the line shows the exact
		customer price with no phantom discount, then hard-lock it after insert in
		case set_missing_values re-fetched a list rate."""
		if self.quotation and frappe.db.exists("Quotation", self.quotation):
			return frappe.get_doc("Quotation", self.quotation)

		quotation_meta = frappe.get_meta("Quotation")
		for fieldname in ("lr_price_sheet", "custom_price_sheet"):
			if quotation_meta.has_field(fieldname):
				existing = frappe.db.get_value("Quotation", {fieldname: self.name}, "name")
				if existing:
					return frappe.get_doc("Quotation", existing)

		quotation = frappe.new_doc("Quotation")
		quotation.quotation_to = "Customer"
		quotation.party_name = self.customer
		quotation.transaction_date = self.transaction_date or nowdate()
		quotation.valid_till = self.valid_till
		if quotation_meta.has_field("order_type"):
			quotation.order_type = "Sales"
		for fieldname in ("lr_price_sheet", "custom_price_sheet"):
			if quotation_meta.has_field(fieldname):
				quotation.set(fieldname, self.name)
		quotation.ignore_pricing_rule = 1
		terms = [
			_("<p><b>Commercial configuration from Price Sheet {0}</b></p>").format(
				frappe.utils.escape_html(self.name)
			),
			"<ul>",
		]
		for line in lines:
			packaging = []
			packaging.append(
				_("Mono Box: {0}").format(line.mono_box_finish or "No Mono Box")
			)
			packaging.append(
				_("Master Box: {0}").format(
					(
						f"{line.master_box_finish} / caselot {line.master_box_caselot}"
						if line.master_box_finish
						else "No Master Box"
					)
				)
			)
			transport = (
				f"{line.transport_type}, zone {line.transport_zone}"
				if line.transport_mode == "Transport"
				else "No Transport"
			)
			payment = f"Credit {line.credit_days} days" if line.credit_days else "Advance"
			terms.append(
				_("<li>{0}: {1}; Transport: {2}; Payment: {3}</li>").format(
					frappe.utils.escape_html(line.item),
					frappe.utils.escape_html("; ".join(packaging)),
					frappe.utils.escape_html(transport),
					frappe.utils.escape_html(payment),
				)
			)
			quotation.append("items", {
				"item_code": line.item,
				"qty": line.customer_agreed_qty,
				"rate": line.customer_price,
				"price_list_rate": line.customer_price,
			})
		terms.append("</ul>")
		quotation.terms = "".join(terms)
		# Approval is explicitly role-gated above; the system creates the standard
		# Quotation even when the approver role has no direct Quotation-create right.
		quotation.flags.ignore_permissions = True
		quotation.insert()

		dirty = False
		for idx, line in enumerate(lines):
			qi = quotation.items[idx]
			if flt(qi.rate) != flt(line.customer_price) or flt(qi.price_list_rate) != flt(line.customer_price):
				qi.rate = line.customer_price
				qi.price_list_rate = line.customer_price
				qi.discount_percentage = 0
				qi.discount_amount = 0
				qi.margin_type = ""
				qi.margin_rate_or_amount = 0
				dirty = True
		if dirty:
			quotation.calculate_taxes_and_totals()
			quotation.save()
		return quotation


def expire_pending_sheets():
	"""Daily scheduler: Pending Approval sheets past their window expire."""
	due = frappe.get_all(
		"Price Sheet",
		filters={
			"status": "Pending Approval",
			"docstatus": 1,
			"valid_till": ("<", nowdate()),
		},
		pluck="name",
	)
	for name in due:
		frappe.db.set_value("Price Sheet", name, "status", "Expired")


@frappe.whitelist()
def get_finish_options(items):
	"""Distinct mono-box finishes available for the selected items (UI helper)."""
	import json

	frappe.has_permission("Price Sheet", "read", throw=True)
	if isinstance(items, str):
		items = json.loads(items)
	if not items:
		return []
	return frappe.get_list(
		"Mono Box Pricing",
		filters={"item": ("in", items)},
		pluck="box_finish",
		distinct=True,
		order_by="box_finish",
		page_length=500,
	)


@frappe.whitelist()
def get_creator_options():
	"""Small, permission-aware option lists used by the guided creator dialog."""
	frappe.has_permission("Price Sheet", "create", throw=True)
	transport_rows = frappe.get_list(
		"Transport Pricing",
		fields=["transport_zone"],
		order_by="transport_zone",
		page_length=500,
	)
	credit_rows = frappe.get_list(
		"Sales Credit Term",
		filters={"payment_type": "Credit"},
		fields=["credit_days", "percentage"],
		order_by="credit_days",
		page_length=100,
	)
	return {
		"transport_zones": sorted(
			{row.transport_zone for row in transport_rows if row.transport_zone}
		),
		"credit_terms": [
			{"credit_days": int(row.credit_days), "percentage": flt(row.percentage)}
			for row in credit_rows
			if row.credit_days
		],
	}


@frappe.whitelist()
def get_master_box_caselot_options(item, finish):
	"""Priced caselots for an approval line; never returns unpriced choices."""
	frappe.has_permission("Price Sheet", "read", throw=True)
	if not item or not finish:
		return []
	return get_master_box_caselots(item, finish)
