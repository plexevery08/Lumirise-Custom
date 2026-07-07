"""Small UI changes from Sai's walkthrough (2026-06-30), codified as Property Setters
so they survive migrate (not UI-only). Idempotent.

  - 2.2  Sales Order order type: default "Sales" + hidden (the 3 order-type options —
         maintenance etc. — are not in the Lumirise flow).
  - 7.6  Purchase Order set_warehouse: hidden (warehouse not needed on the PO header).
  - Material Request Purpose (material_request_type): default "Material Transfer"
         (Lumirise MRs are shopfloor transfers; 2026-07-07).
  - 1.6  BOM "Secondary Items" section: hidden (scrap/co-products are auto-populated —
         should never require manual entry; the empty row forced a delete-before-save).
         Hides the section break + the table + its two cost read-outs.

Note: the Purchase Order Container No (lr_container_no) and PI Number (lr_pi_number) fields
were REMOVED entirely on 2026-07-07 (client request), so their earlier "hide" tweaks are gone.

Each entry is (doctype, fieldname, property, value, property_type).
"""

import frappe

PROPERTY_SETTERS = [
	("Sales Order", "order_type", "default", "Sales", "Data"),
	("Sales Order", "order_type", "hidden", "1", "Check"),
	("Purchase Order", "set_warehouse", "hidden", "1", "Check"),
	("Material Request", "material_request_type", "default", "Material Transfer", "Data"),
	# Vendor PDI purchase_order read-only is now baked into the doctype JSON (2026-07-07).
	# 1.6 — remove the BOM "Secondary Items" section from the entry form
	("BOM", "section_break_hygk", "hidden", "1", "Check"),
	("BOM", "secondary_items", "hidden", "1", "Check"),
	("BOM", "secondary_items_cost", "hidden", "1", "Check"),
	("BOM", "base_secondary_items_cost", "hidden", "1", "Check"),
]


def apply_ui_tweaks():
	for doctype, fieldname, prop, value, ptype in PROPERTY_SETTERS:
		# skip silently if the field doesn't exist on this site's version
		if not frappe.get_meta(doctype).get_field(fieldname):
			continue
		frappe.make_property_setter(
			{
				"doctype": doctype,
				"fieldname": fieldname,
				"property": prop,
				"value": value,
				"property_type": ptype,
			},
			is_system_generated=False,
		)
