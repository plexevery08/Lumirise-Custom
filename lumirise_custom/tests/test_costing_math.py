import unittest

from lumirise_custom.costing_math import (
	calculate_bom_cost,
	calculate_import_cost,
	effective_exchange_rate,
	round_cost,
	select_price_book_row,
)


class CostingMathTest(unittest.TestCase):
	def test_import_cost_formula(self):
		self.assertEqual(
			calculate_import_cost(10, 12, 10),
			{"price_in_inr": 120.0, "duty_amount": 12.0, "landed_cost": 132.0},
		)

	def test_commercial_rounding_is_half_up(self):
		self.assertEqual(round_cost("1.2345", 3), 1.235)

	def test_global_exchange_rate_can_be_enforced_or_overridden(self):
		self.assertEqual(effective_exchange_rate(11.5, 12.25, True), 11.5)
		self.assertEqual(effective_exchange_rate(11.5, 12.25, False), 12.25)
		self.assertEqual(effective_exchange_rate(0, 12.25, True), 12.25)

	def test_sub_bom_is_normalized_by_output_quantity(self):
		result = calculate_bom_cost(
			raw_materials_batch_total=300,
			output_qty=10,
			bom_type="Sub BOM",
			conversion_cost=2,
		)
		self.assertEqual(result["raw_materials_batch_total"], 300.0)
		self.assertEqual(result["raw_materials_unit_total"], 30.0)
		self.assertEqual(result["rollup_cost"], 32.0)

	def test_parent_layers_compound_in_business_order(self):
		result = calculate_bom_cost(
			raw_materials_batch_total=100,
			output_qty=2,
			bom_type="Parent BOM",
			inward_transport_cost=5,
			factory_overheads=5,
			layers=[("dollar", 10), ("interest", 5)],
			moq_percentages={"1k": 12},
		)
		self.assertEqual(result["raw_materials_unit_total"], 50.0)
		self.assertEqual(result["layers"]["dollar"], {"base": 60.0, "value": 6.0, "total": 66.0})
		self.assertEqual(result["layers"]["interest"], {"base": 66.0, "value": 3.3, "total": 69.3})
		self.assertEqual(result["final_cost"], 69.3)
		self.assertEqual(result["moq_prices"]["1k"], 77.616)

	def test_price_book_resolution_uses_range_then_preferred_vendor(self):
		rows = [
			{"name": "cheap-wrong-range", "min_qty": 1, "max_qty": 999, "preferred": 1, "rate": 5, "idx": 1},
			{
				"name": "matching-cheapest",
				"min_qty": 1000,
				"max_qty": 5000,
				"preferred": 0,
				"rate": 8,
				"idx": 2,
			},
			{
				"name": "matching-preferred",
				"min_qty": 1000,
				"max_qty": 5000,
				"preferred": 1,
				"rate": 9,
				"idx": 3,
			},
		]
		self.assertEqual(select_price_book_row(rows, 3000)["name"], "matching-preferred")


if __name__ == "__main__":
	unittest.main()
