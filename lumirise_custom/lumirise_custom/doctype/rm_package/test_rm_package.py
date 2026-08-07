import unittest

import frappe


class TestRMPackage(unittest.TestCase):
	"""Schema/controller smoke checks that do not seed or mutate business data."""

	def test_doctype_is_installed(self):
		self.assertTrue(frappe.db.exists("DocType", "RM Package"))
		meta = frappe.get_meta("RM Package")
		for field in ("package_barcode", "item_code", "batch_no", "current_warehouse", "status"):
			self.assertIsNotNone(meta.get_field(field))
