from unittest import TestCase
from unittest.mock import patch

import frappe

from lumirise_custom import costing


class CostSourceResolutionTest(TestCase):
	def setUp(self):
		self.settings = frappe._dict(
			precision=3,
			default_rmb_to_inr_rate=12,
			use_global_rmb_to_inr_rate=1,
			sync_costing_rate_to_valuation_rate=0,
			default_moq_percentages=costing.DEFAULT_MOQ_PERCENTAGES,
		)

	@patch("lumirise_custom.costing.get_approved_price_book_cost")
	def test_approved_price_book_wins(self, price_book_cost):
		price_book_cost.return_value = frappe._dict(
			rate=88, source=costing.SOURCE_PRICE_BOOK, reference="RMPB-1 / ROW-1"
		)
		item = frappe._dict(
			custom_price_in_rmb=10,
			custom_rmb_to_inr_rate=12,
			custom_custom_duty=10,
			custom_last_purchase_cost=100,
			valuation_rate=90,
		)
		result = costing.resolve_item_cost("RM-1", item_doc=item, settings=self.settings)
		self.assertEqual((result.rate, result.source), (88, costing.SOURCE_PRICE_BOOK))

	@patch("lumirise_custom.costing.get_approved_price_book_cost", return_value=None)
	def test_import_then_purchase_then_valuation_fallback(self, _price_book_cost):
		import_item = frappe._dict(
			custom_price_in_rmb=10,
			custom_rmb_to_inr_rate=0,
			custom_custom_duty=10,
			custom_last_purchase_cost=100,
			valuation_rate=90,
		)
		result = costing.resolve_item_cost("RM-1", item_doc=import_item, settings=self.settings)
		self.assertEqual((result.rate, result.source), (132.0, costing.SOURCE_IMPORT))

		purchase_item = frappe._dict(
			custom_price_in_rmb=0,
			custom_last_purchase_cost=100,
			valuation_rate=90,
		)
		result = costing.resolve_item_cost("RM-2", item_doc=purchase_item, settings=self.settings)
		self.assertEqual((result.rate, result.source), (100.0, costing.SOURCE_PURCHASE))

		valuation_item = frappe._dict(
			custom_price_in_rmb=0,
			custom_last_purchase_cost=0,
			valuation_rate=90,
		)
		result = costing.resolve_item_cost("RM-3", item_doc=valuation_item, settings=self.settings)
		self.assertEqual((result.rate, result.source), (90.0, costing.SOURCE_VALUATION))


class CostingCascadeTest(TestCase):
	@patch("lumirise_custom.costing._persist_bom_costing")
	@patch("lumirise_custom.costing.compute_bom_costing")
	@patch("lumirise_custom.costing.frappe.get_doc")
	@patch("lumirise_custom.costing._parent_bom_names")
	def test_cascade_recomputes_every_ancestor_once(self, parent_names, get_doc, compute, persist):
		parent_names.side_effect = lambda bom, _item: {
			"SUB": {"PARENT"},
			"PARENT": {"TOP"},
			"TOP": set(),
		}[bom]
		docs = {
			"PARENT": frappe._dict(name="PARENT", item="MID", is_active=1, docstatus=1),
			"TOP": frappe._dict(name="TOP", item="FG", is_active=1, docstatus=1),
		}
		get_doc.side_effect = lambda _doctype, name: docs[name]

		processed = costing._cascade_to_parents("SUB", "SUB-ITEM")

		self.assertEqual(processed, {"PARENT", "TOP"})
		self.assertEqual([call.args[0].name for call in compute.call_args_list], ["PARENT", "TOP"])
		self.assertEqual(persist.call_count, 2)
