# Copyright (c) 2026, riddhi solanki and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from lumirise_custom.pricing_engine import (
	_configuration_contexts,
	_parse_caselots,
	calculate_approval_price,
	moq_for_quantity,
)


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestPriceSheet(IntegrationTestCase):
	def test_moq_boundaries_and_sample_exception_floor(self):
		self.assertIsNone(moq_for_quantity(999))
		self.assertEqual(moq_for_quantity(1000), 1000)
		self.assertEqual(moq_for_quantity(2999), 1000)
		self.assertEqual(moq_for_quantity(3000), 3000)
		self.assertEqual(moq_for_quantity(10000), 10000)

	def test_caselot_parser_deduplicates_and_rejects_invalid_values(self):
		self.assertEqual(_parse_caselots("100, 50,100,abc,0"), [50, 100])

	@patch("lumirise_custom.pricing_engine.get_item_mono_finishes", return_value=["MATT"])
	@patch("lumirise_custom.pricing_engine.get_master_box_caselots", return_value=[50, 100])
	def test_queue_preserves_each_product_group_configuration(self, _caselots, _finishes):
		sheet = frappe._dict(
			configurations=[
				frappe._dict(
					configuration_group="Group 1",
					item="ITEM-A",
					master_box_finish="5 Ply",
					master_box_caselots="",
					delivery_type="Transport",
					transport_type="Private",
					transport_zone="South",
					payment_type="Credit",
					credit_days=45,
				),
				frappe._dict(
					configuration_group="Group 2",
					item="ITEM-B",
					master_box_finish=None,
					master_box_caselots="",
					delivery_type="Ex-Factory",
					payment_type="Advance",
					credit_days=0,
				),
			]
		)
		contexts = list(_configuration_contexts(sheet))
		self.assertEqual(contexts[0].configuration_group, "Group 1")
		self.assertEqual(contexts[0].caselots, [50, 100])
		self.assertEqual(contexts[0].transport_zone, "South")
		self.assertEqual(contexts[1].configuration_group, "Group 2")
		self.assertEqual(contexts[1].delivery_type, "Ex-Factory")

	@patch(
		"lumirise_custom.pricing_engine.get_settings",
		return_value=frappe._dict(no_master_box_extra_cost=0.8),
	)
	@patch("lumirise_custom.pricing_engine.get_base_price", return_value=(0.0, "None"))
	def test_approval_refuses_zero_base_price(self, _base, _settings):
		with self.assertRaises(frappe.ValidationError):
			calculate_approval_price(
				item="ITEM-A",
				moq=1000,
				mono_box_finish=None,
				master_box_finish=None,
				master_box_caselot=None,
				transport_mode="No Transport",
				transport_type=None,
				transport_zone=None,
				credit_days=0,
			)

	@patch(
		"lumirise_custom.pricing_engine.get_settings",
		return_value=frappe._dict(no_master_box_extra_cost=0.8),
	)
	@patch("lumirise_custom.pricing_engine.get_base_price", return_value=(100.0, "Base Price"))
	@patch("lumirise_custom.pricing_engine.get_no_box_profit", return_value=1.0)
	@patch(
		"lumirise_custom.pricing_engine.get_master_box_data",
		return_value=frappe._dict(price=None, cost_per_light=None, found=False),
	)
	def test_selected_missing_master_box_never_becomes_zero_cost(
		self, _master, _profit, _base, _settings
	):
		with self.assertRaises(frappe.ValidationError):
			calculate_approval_price(
				item="ITEM-A",
				moq=1000,
				mono_box_finish=None,
				master_box_finish="5 Ply",
				master_box_caselot=50,
				transport_mode="No Transport",
				transport_type=None,
				transport_zone=None,
				credit_days=0,
			)
