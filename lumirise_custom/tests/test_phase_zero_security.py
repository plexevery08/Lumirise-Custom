from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import frappe
from frappe.tests import IntegrationTestCase

from lumirise_custom import chain
from lumirise_custom.action_permissions import (
	require_logistics_action,
	require_purchase_release,
	require_quality_action,
)
from lumirise_custom.lumirise_custom.doctype.material_planning.material_planning import (
	MaterialPlanning,
)
from lumirise_custom.setup import before_migrate
from lumirise_custom.setup.approval_setup import APPROVAL_ROLES

MANAGED_WORKFLOWS = (
	"Indent Approval",
	"Purchase Order Release",
	"RM Price Book Approval",
	"Material Planning Approval",
)

EXPECTED_OPERATIONAL_PERMISSIONS = {
	"IQC": {
		"Quality Inspector": {"create", "read", "write", "submit"},
		"Quality Manager": {"create", "read", "write", "submit", "cancel", "amend"},
	},
	"Vendor PDI": {
		"Purchase User": {"create", "read"},
		"Quality Inspector": {"create", "read", "write", "submit"},
		"Quality Manager": {"create", "read", "write", "submit", "cancel", "amend"},
	},
	"Inbound Logistics": {
		"Logistics User": {"create", "read", "write", "submit"},
		"Logistics Manager": {"create", "read", "write", "submit", "cancel", "amend"},
		"Purchase User": {"read", "write"},
	},
	"Indent": {
		"Planning User": {"create", "read", "write"},
		"Planning Manager": {"create", "read", "write", "submit", "cancel", "amend"},
		"Purchase User": {"read"},
	},
	"Customer PDI": {
		"Lumirise Operations": {"create", "read", "write"},
		"Factory Store Manager": {"read", "write"},
		"Quality Inspector": {"create", "read", "write"},
	},
}


class TestPhaseZeroSecurity(IntegrationTestCase):
	def test_operational_doctypes_are_not_system_manager_only(self):
		for doctype, expected_roles in EXPECTED_OPERATIONAL_PERMISSIONS.items():
			permissions = {row.role: row for row in frappe.get_meta(doctype).permissions}
			self.assertTrue(set(permissions) - {"System Manager"}, doctype)
			for role, expected_actions in expected_roles.items():
				self.assertIn(role, permissions, f"{doctype}: missing {role}")
				for action in expected_actions:
					self.assertEqual(
						permissions[role].get(action),
						1,
						f"{doctype}: {role} requires {action}",
					)

	def test_custom_operational_roles_exist_before_schema_sync(self):
		# Frappe's own test cleanup uses and may remove a Role named "Security User".
		# Exercise the real pre-migrate hook so this remains deterministic in a full run.
		before_migrate()
		for role in APPROVAL_ROLES:
			self.assertTrue(frappe.db.exists("Role", role), role)

	def test_managed_workflows_disallow_self_approval_for_decisions(self):
		for workflow_name in MANAGED_WORKFLOWS:
			workflow = frappe.get_doc("Workflow", workflow_name)
			self.assertTrue(workflow.transitions, workflow_name)
			for transition in workflow.transitions:
				if transition.action.startswith("Submit for "):
					continue
				self.assertFalse(
					transition.allow_self_approval,
					f"{workflow_name}: {transition.state} / {transition.action}",
				)

	def test_makers_can_send_their_own_drafts_to_the_queue(self):
		for workflow_name in MANAGED_WORKFLOWS:
			workflow = frappe.get_doc("Workflow", workflow_name)
			maker_handoffs = [
				transition
				for transition in workflow.transitions
				if transition.action.startswith("Submit for ")
			]
			self.assertTrue(maker_handoffs, workflow_name)
			for transition in maker_handoffs:
				self.assertTrue(
					transition.allow_self_approval,
					f"{workflow_name}: maker cannot send draft with {transition.action}",
				)

	def test_indent_uses_separate_maker_and_checker_roles(self):
		workflow = frappe.get_doc("Workflow", "Indent Approval")
		transitions = {(row.state, row.action): row.allowed for row in workflow.transitions}
		self.assertEqual(transitions[("Draft", "Submit for Approval")], "Planning User")
		self.assertEqual(
			transitions[("Pending Planning Manager", "Planning Manager Approve")],
			"Planning Manager",
		)

	def test_generated_indent_keeps_the_planning_user_as_owner(self):
		planning = SimpleNamespace(
			name="PLAN-TEST",
			owner="planner@example.com",
			branch=None,
			fg_plan=[],
			components=[
				frappe._dict(
					to_be_ordered=10,
					component_item="RM-TEST",
					fg_item="FG-TEST",
					sales_order="SO-TEST",
				)
			],
		)
		indent = SimpleNamespace(name="IND-TEST", insert=Mock())
		with (
			patch(
				"lumirise_custom.lumirise_custom.doctype.material_planning.material_planning.frappe.get_doc",
				return_value=indent,
			) as get_doc,
			patch(
				"lumirise_custom.lumirise_custom.doctype.material_planning.material_planning.frappe.db.get_value",
				return_value="BOM-TEST",
			),
			patch(
				"lumirise_custom.lumirise_custom.doctype.material_planning.material_planning.config.get_company",
				return_value="Lumirise",
			),
			patch(
				"lumirise_custom.lumirise_custom.doctype.material_planning.material_planning.config.item_uom",
				return_value="Nos",
			),
			patch(
				"lumirise_custom.lumirise_custom.doctype.material_planning.material_planning._lead_days",
				return_value=5,
			),
			patch(
				"lumirise_custom.lumirise_custom.doctype.material_planning.material_planning.nowdate",
				return_value="2026-08-10",
			),
		):
			result = MaterialPlanning._create_consolidated_indent(planning)

		self.assertEqual(result, "IND-TEST")
		self.assertEqual(get_doc.call_args.args[0]["owner"], "planner@example.com")
		indent.insert.assert_called_once_with(ignore_permissions=True)

	def test_action_role_guards_reject_the_wrong_department(self):
		guards = (require_quality_action, require_logistics_action, require_purchase_release)
		with patch("lumirise_custom.action_permissions.frappe.get_roles", return_value=["Sales User"]):
			for guard in guards:
				with self.assertRaises(frappe.PermissionError):
					guard()

	def test_mapping_guard_checks_source_and_target_permissions(self):
		with patch("lumirise_custom.chain.frappe.has_permission") as has_permission:
			chain._require_mapping_permissions("Purchase Order", "PO-0001", "Vendor PDI")
		has_permission.assert_has_calls(
			[
				call("Purchase Order", "read", "PO-0001", throw=True),
				call("Vendor PDI", "create", throw=True),
			]
		)
