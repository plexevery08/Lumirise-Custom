# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Vendor PDI = pre-dispatch inspection at the vendor's place (incl. China).
# First gate of the inbound chain: Vendor PDI -> Inbound Logistics -> IQC -> GRN.
# Focus rule: approved qty can never exceed the PO qty (less is allowed).

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class VendorPDI(Document):
	def validate(self):
		for row in self.items:
			po_qty = flt(frappe.db.get_value(
				"Purchase Order Item",
				{"parent": self.purchase_order, "item_code": row.item_code}, "qty"))
			if po_qty:
				row.po_qty = po_qty
			if flt(row.approved_qty) > flt(row.po_qty):
				frappe.throw(
					f"Row {row.idx} ({row.item_code}): Approved Qty {row.approved_qty} "
					f"cannot exceed PO Qty {row.po_qty}.")
