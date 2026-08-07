import frappe
from frappe.tests import IntegrationTestCase

from lumirise_custom.rm_barcode import _clean_code


class IntegrationTestRMReceivingPackage(IntegrationTestCase):
	def test_code_cleanup_is_label_safe(self):
		self.assertEqual(_clean_code("ITEM / 10 (China)"), "ITEM-10-China")

	def test_qc_quantities_cannot_exceed_received(self):
		doc = frappe.get_doc(
			{
				"doctype": "RM Receiving Package",
				"inbound_logistics": "TEST-INBOUND",
				"item_code": "TEST-ITEM",
				"received_qty": 10,
				"accepted_qty": 7,
				"rejected_qty": 4,
				"remaining_qty": 0,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.run_method("validate")
