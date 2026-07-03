import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from lumirise_custom.pricing_engine import (
	calculate_approval_price,
	generate_rows,
	get_settings,
	moq_for_quantity,
)

APPROVER_ROLES = ("Sales Approver", "System Manager")


class PriceSheet(Document):
	def validate(self):
		self.set_valid_till()
		if self.docstatus == 0:
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
		if not self.products:
			frappe.throw(_("Select at least one product"))
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
		if not set(APPROVER_ROLES) & set(frappe.get_roles()):
			frappe.throw(_("Only a Sales Approver can do this"), frappe.PermissionError)

	def check_window(self):
		if self.status != "Pending Approval":
			frappe.throw(_("Only pending price sheets can be approved or rejected"))
		if getdate(nowdate()) > getdate(self.valid_till):
			self.db_set("status", "Expired")
			frappe.throw(_("This price sheet's approval window has expired"))

	@frappe.whitelist()
	def populate_approval_items(self):
		"""Prefill one approval line per product from the sheet configuration."""
		self.check_approver()
		if self.approval_items:
			return
		for product in self.products:
			self.append("approval_items", {
				"item": product.item,
				"give_to_customer": 1,
				"mono_box_finish": (
					self.mono_box_finishes[0].box_finish if self.mono_box_finishes else None
				),
				"master_box_finish": self.master_box_finish,
				"master_box_caselot": int(str(self.master_box_caselots).split(",")[0])
				if self.master_box_finish and (self.master_box_caselots or "").strip()
				else None,
				"transport_mode": "Transport" if self.delivery_type == "Transport" else "No Transport",
				"transport_type": self.transport_type,
				"transport_zone": self.transport_zone,
				"credit_days": self.credit_days,
				"listening_percentage": self.listening_percentage,
			})
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

			if flt(line.customer_agreed_qty) < settings.min_agreed_qty:
				frappe.throw(
					_("Row {0} ({1}): customer agreed quantity must be at least {2}").format(
						line.idx, line.item, settings.min_agreed_qty
					)
				)
			if not flt(line.customer_price) and not for_preview:
				frappe.throw(
					_("Row {0} ({1}): customer price is required").format(line.idx, line.item)
				)

			line.selected_moq = moq_for_quantity(line.customer_agreed_qty)
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
		self.check_window()
		selected = [l for l in (self.approval_items or []) if l.give_to_customer]
		if not selected:
			frappe.throw(_("Add at least one approval line marked Give To Customer"))

		self.compute_approval_lines()
		self.save()

		quotation = self.make_quotation(selected)
		self.db_set("status", "Approved")
		self.db_set("approved_by", frappe.session.user)
		self.db_set("approved_at", now_datetime())
		self.db_set("quotation", quotation.name)
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
		negotiated customer price. One-way reference only (design rule:
		no reverse links between custom doctypes).

		The Price Sheet IS the pricing authority — so the Quotation must NOT let
		ERPNext's own Item Price / Pricing Rules re-price the line (that once turned
		a negotiated 150 into a demo Pricing-Rule's 570). We set ignore_pricing_rule
		and pin price_list_rate = the negotiated rate so the line shows the exact
		customer price with no phantom discount, then hard-lock it after insert in
		case set_missing_values re-fetched a list rate."""
		quotation = frappe.new_doc("Quotation")
		quotation.quotation_to = "Customer"
		quotation.party_name = self.customer
		quotation.transaction_date = nowdate()
		quotation.custom_price_sheet = self.name
		quotation.ignore_pricing_rule = 1
		for line in lines:
			quotation.append("items", {
				"item_code": line.item,
				"qty": line.customer_agreed_qty,
				"rate": line.customer_price,
				"price_list_rate": line.customer_price,
			})
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

	if isinstance(items, str):
		items = json.loads(items)
	if not items:
		return []
	return frappe.get_all(
		"Mono Box Pricing",
		filters={"item": ("in", items)},
		pluck="box_finish",
		distinct=True,
		order_by="box_finish",
	)
