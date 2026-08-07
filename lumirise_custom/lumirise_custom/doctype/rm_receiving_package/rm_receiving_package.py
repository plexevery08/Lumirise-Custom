import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class RMReceivingPackage(Document):
	def before_insert(self):
		if not self.flags.get("rm_barcode_system_update"):
			frappe.throw(_("RM package records must be created through an authorised barcode workflow."))
		if not self.barcode_value:
			self.barcode_value = self.name

	def validate(self):
		if not self.is_new() and not self.flags.get("rm_barcode_system_update"):
			frappe.throw(_("RM package records are scan-controlled and cannot be edited manually."))
		if flt(self.received_qty) <= 0:
			frappe.throw(_("Package quantity must be greater than zero."))
		if flt(self.accepted_qty) + flt(self.rejected_qty) > flt(self.received_qty) + 0.001:
			frappe.throw(_("Accepted plus rejected quantity cannot exceed received quantity."))
		if flt(self.remaining_qty) < -0.001:
			frappe.throw(_("Remaining quantity cannot be negative."))
		if flt(self.conversion_factor) <= 0:
			frappe.throw(_("Purchase-to-stock conversion factor must be greater than zero."))
		if self.batch_no:
			batch_item = frappe.db.get_value("Batch", self.batch_no, "item")
			if batch_item and batch_item != self.item_code:
				frappe.throw(
					_("Batch {0} belongs to item {1}, not {2}.").format(
						self.batch_no, batch_item, self.item_code
					)
				)

	def after_insert(self):
		# autoname is only final after insertion; keep the physical code equal to the
		# immutable package ID unless an administrator deliberately supplied one.
		if not self.barcode_value:
			self.db_set("barcode_value", self.name, update_modified=False)

	def on_trash(self):
		if not self.flags.get("rm_barcode_system_update"):
			frappe.throw(_("RM package audit records cannot be deleted manually."))
