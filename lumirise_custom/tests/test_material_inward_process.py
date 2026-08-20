from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from lumirise_custom import inward_process
from lumirise_custom.lumirise_custom.doctype.rm_package.rm_package import _resolve_location


class TestMaterialInwardProcess(IntegrationTestCase):
	def test_process_schema_is_migrated(self):
		inbound_meta = frappe.get_meta("Inbound Logistics")
		for fieldname in (
			"inward_stage",
			"gate_verified_on",
			"invoice_verified",
			"iqc_task",
			"unloading_status",
			"physical_verification_status",
			"inward_exceptions",
			"rack_warehouse",
			"purchase_receipt",
			"final_signoff",
		):
			self.assertTrue(inbound_meta.has_field(fieldname), fieldname)
		self.assertEqual(inbound_meta.get_field("inward_exceptions").options, "Inbound Process Exception")

		package_meta = frappe.get_meta("RM Package")
		for fieldname in ("label_printed", "label_applied", "label_applied_by", "label_applied_on"):
			self.assertTrue(package_meta.has_field(fieldname), fieldname)

	def test_security_role_can_read_and_update_gate_record(self):
		permissions = {row.role: row for row in frappe.get_meta("Inbound Logistics").permissions}
		self.assertIn("Security User", permissions)
		self.assertEqual(permissions["Security User"].read, 1)
		self.assertEqual(permissions["Security User"].write, 1)

	def test_seeded_location_barcode_resolves_to_leaf_rack(self):
		self.assertEqual(_resolve_location("RACK-A-01"), "RM Rack A-01 - L")
		self.assertFalse(frappe.db.get_value("Warehouse", "RM Rack A-01 - L", "is_group"))

	def test_transport_damage_requires_photo_evidence(self):
		doc = frappe._dict(
			items=[frappe._dict(item_code="RM-TEST")],
			inward_exceptions=[
				frappe._dict(
					idx=1,
					item_code="RM-TEST",
					exception_qty=2,
					exception_type="Transport Damage",
					evidence=None,
					status="Open",
					resolution_reference=None,
				)
			],
			rack_warehouse=None,
		)
		with self.assertRaises(frappe.ValidationError):
			inward_process.validate_inbound(doc)

	def test_grn_is_blocked_when_poster_controls_are_missing(self):
		log = frappe._dict(
			name="LOG-TEST",
			vehicle_gate_status="Pending Approval",
			gate_verified_on=None,
			document_verification_status="Pending",
			iqc_task=None,
			iqc_reference=None,
			unloading_status="Pending",
			physical_verified_on=None,
			invoice_price_verified=0,
			storage_authorized=0,
		)
		grn = frappe._dict(is_subcontracted=0, lr_iqc=None, items=[])
		with (
			patch.object(inward_process, "_logs_for_grn", return_value=[log]),
			self.assertRaises(frappe.ValidationError),
		):
			inward_process.inward_grn_gate(grn)

	def test_grn_requires_package_coverage_equal_to_iqc_acceptance(self):
		log = frappe._dict(
			name="LOG-TEST",
			vehicle_gate_status="Approved",
			gate_verified_on="2026-08-10 10:00:00",
			document_verification_status="Verified",
			iqc_task="LTASK-TEST",
			iqc_reference="IQC-TEST",
			unloading_status="Completed",
			physical_verified_on="2026-08-10 11:00:00",
			invoice_price_verified=1,
			storage_authorized=1,
		)
		grn = frappe._dict(is_subcontracted=0, lr_iqc="IQC-TEST", items=[])
		with (
			patch.object(inward_process, "_logs_for_grn", return_value=[log]),
			patch.object(inward_process, "_passed_iqc", return_value=frappe._dict(name="IQC-TEST")),
			patch.object(
				inward_process,
				"package_coverage",
				return_value=({"RM-TEST": 10}, {"RM-TEST": 9}, [frappe._dict(name="LPN-1")], []),
			),
			self.assertRaises(frappe.ValidationError),
		):
			inward_process.inward_grn_gate(grn)
