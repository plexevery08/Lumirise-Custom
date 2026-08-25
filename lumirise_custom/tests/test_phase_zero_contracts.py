import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

import lumirise_custom
from lumirise_custom import feature_flags
from lumirise_custom.action_permissions import require_stock_entry_permissions
from lumirise_custom.action_registry import (
	ACTION_REGISTRY,
	EASY_UI_APPROVED_ACTIONS,
	ENDPOINT_INVENTORY,
	require_easy_ui_action,
)
from lumirise_custom.audit_events import build_audit_event
from lumirise_custom.lumirise_custom.doctype.bom_change_request import bom_change_request
from lumirise_custom.patches.backfill_phase_zero_task_contracts import build_backfill_plan, pending_count
from lumirise_custom.quantity_contracts import QUANTITY_SOURCES, availability, incoming_buckets
from lumirise_custom.task_contracts import (
	BLOCKER_REASONS,
	RESOLUTION_REASONS,
	synchronize_owner_assignment,
	task_view,
)


def _whitelisted_app_methods():
	root = Path(lumirise_custom.__file__).parent
	methods = set()
	for path in root.rglob("*.py"):
		if any(part in {"demo", "patches", "tests"} for part in path.parts):
			continue
		tree = ast.parse(path.read_text())
		module = ".".join(path.relative_to(root.parent).with_suffix("").parts)
		for node in ast.walk(tree):
			if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
				continue
			for decorator in node.decorator_list:
				target = decorator.func if isinstance(decorator, ast.Call) else decorator
				if (isinstance(target, ast.Attribute) and target.attr == "whitelist") or (
					isinstance(target, ast.Name) and target.id == "whitelist"
				):
					methods.add(f"{module}.{node.name}")
					break
	return methods


class TestPhaseZeroFeatureFlags(IntegrationTestCase):
	def test_every_named_rollout_flag_exists_and_defaults_off(self):
		meta = frappe.get_meta(feature_flags.SETTINGS_DOCTYPE)
		for flag in feature_flags.KNOWN_FLAGS:
			field = meta.get_field(flag)
			self.assertIsNotNone(field, flag)
			# A site may intentionally enable a read-only pilot surface. The
			# source DocType default is the release contract and must remain off.
			self.assertIn(str(field.default or "0").lower(), {"0", "false", "none"}, flag)

	def test_read_visibility_and_actions_are_independent(self):
		self.assertTrue(feature_flags.READ_SURFACE_FLAGS)
		self.assertTrue(feature_flags.ACTION_FLAGS)
		self.assertTrue(feature_flags.READ_SURFACE_FLAGS.isdisjoint(feature_flags.ACTION_FLAGS))

		with (
			patch.object(frappe, "get_meta", return_value=SimpleNamespace(has_field=lambda _flag: True)),
			patch.object(
				frappe.db,
				"get_single_value",
				side_effect=lambda _doctype, flag: 1 if flag == "easy_ui_my_work" else 0,
			),
		):
			self.assertTrue(feature_flags.is_enabled("easy_ui_my_work"))
			self.assertFalse(feature_flags.is_enabled("easy_ui_state_actions"))

	def test_unknown_flags_fail_closed(self):
		self.assertFalse(feature_flags.is_enabled("unregistered_action"))
		with self.assertRaises(frappe.ValidationError):
			feature_flags.require_enabled("unregistered_action")


class TestPhaseZeroActionRegistry(IntegrationTestCase):
	def test_every_whitelisted_app_endpoint_is_inventoried(self):
		self.assertSetEqual(set(ENDPOINT_INVENTORY), _whitelisted_app_methods())

	def test_state_actions_are_inventoried_but_fail_closed(self):
		self.assertTrue(ACTION_REGISTRY)
		for action_id, contract in ACTION_REGISTRY.items():
			self.assertEqual(action_id, contract.action_id)
			self.assertEqual(contract.approved_for_easy_ui, action_id in EASY_UI_APPROVED_ACTIONS)
			self.assertEqual(contract.feature_flag, "easy_ui_state_actions")
			self.assertTrue(contract.authorized_roles, action_id)
			self.assertTrue(contract.effect_summary, action_id)
			self.assertTrue(contract.reversal_route, action_id)

		with self.assertRaises(frappe.PermissionError):
			require_easy_ui_action("stock.put_away_package", "RM-PACKAGE-TEST")

	def test_audit_event_contract_requires_reason_and_records_before_after(self):
		with self.assertRaises(frappe.ValidationError):
			build_audit_event(
				"engineering.reject_change",
				source_doctype="BOM Change Request",
				source_name="BCR-TEST",
			)

		event = build_audit_event(
			"engineering.reject_change",
			source_doctype="BOM Change Request",
			source_name="BCR-TEST",
			actor="checker@example.com",
			reason_code="incorrect_quantity",
			reason_note="The proposed component quantity does not match the drawing.",
			before={"workflow_state": "Pending Change Approval"},
			after={"workflow_state": "Rejected"},
		)
		self.assertEqual(event["schema_version"], 1)
		self.assertEqual(event["action_id"], "engineering.reject_change")
		self.assertEqual(event["actor"], "checker@example.com")
		self.assertEqual(event["before"]["workflow_state"], "Pending Change Approval")
		self.assertEqual(event["after"]["workflow_state"], "Rejected")


class TestPhaseZeroQuantityContract(IntegrationTestCase):
	def test_availability_preserves_signed_deficit_and_exclusive_outputs(self):
		result = availability(
			on_hand=100,
			unusable_on_hand=10,
			committed=60,
			reserved=40,
			incoming=25,
			additional_demand=20,
		)
		self.assertEqual(result["usable_on_hand"], 90)
		self.assertEqual(result["raw_free"], -10)
		self.assertEqual(result["free_now"], 0)
		self.assertEqual(result["projected_raw"], -5)
		self.assertEqual(result["projected_surplus"], 0)
		self.assertEqual(result["shortfall"], 5)

	def test_incoming_stages_do_not_double_count_the_open_po_anchor(self):
		buckets = incoming_buckets(100, pending_pdi=20, in_transit=30, pending_iqc=10)
		self.assertEqual(buckets["pending_order"], 40)
		self.assertEqual(buckets["incoming"], 100)
		self.assertEqual(buckets["overlap_qty"], 0)

	def test_incoming_surfaces_a_stage_total_above_the_open_po(self):
		buckets = incoming_buckets(50, pending_pdi=20, in_transit=40)
		self.assertEqual(buckets["pending_order"], 0)
		self.assertEqual(buckets["incoming"], 60)
		self.assertEqual(buckets["overlap_qty"], 10)

	def test_quantity_sources_keep_commitments_and_reservations_separate(self):
		self.assertNotIn("Bin.reserved_qty", QUANTITY_SOURCES["committed"])
		self.assertEqual(QUANTITY_SOURCES["reserved"], ("Bin.reserved_qty",))


class TestPhaseZeroTaskContract(IntegrationTestCase):
	def test_due_on_is_canonical_and_severity_is_independent(self):
		task = frappe.get_doc(
			{
				"doctype": "Lumirise Task",
				"title": "Phase 0 contract test",
				"status": "Open",
				"priority": "Urgent",
				"due_date": "2026-08-20",
			}
		).insert(ignore_permissions=True)

		# Priority is urgency; severity is an independent impact classification.
		self.assertEqual(task.severity, "Medium")
		self.assertEqual(str(task.due_on), "2026-08-20 23:59:59")
		self.assertEqual(str(task.due_date), "2026-08-20")

		task.reload()
		task.severity = "Low"
		task.priority = "Urgent"
		task.save(ignore_permissions=True)
		self.assertEqual(task.severity, "Low")

	def test_blocked_requires_a_stable_code_and_reason(self):
		task = frappe.get_doc(
			{"doctype": "Lumirise Task", "title": "Blocked contract test", "status": "Open"}
		).insert(ignore_permissions=True)
		task.status = "Blocked"
		with self.assertRaises(frappe.ValidationError):
			task.save(ignore_permissions=True)

		task.reload()
		task.status = "Blocked"
		task.blocker_code = "dependency_pending"
		task.blocker_reason = "Waiting for the approved source document."
		task.review_on = add_to_date(now_datetime(), hours=2)
		task.save(ignore_permissions=True)
		self.assertEqual(task_view(task.status, task.review_on), "waiting")

	def test_terminal_task_records_resolution_identity(self):
		task = frappe.get_doc(
			{"doctype": "Lumirise Task", "title": "Resolution contract test", "status": "Open"}
		).insert(ignore_permissions=True)
		task.status = "Done"
		task.save(ignore_permissions=True)
		self.assertEqual(task.resolution_code, "completed")
		self.assertEqual(task.resolved_by, frappe.session.user)
		self.assertTrue(task.resolved_on)
		self.assertTrue(task.completed_on)

	def test_waiting_is_a_view_not_a_persisted_status(self):
		future = add_to_date(now_datetime(), hours=1)
		past = add_to_date(now_datetime(), hours=-1)
		self.assertEqual(task_view("Blocked", future), "waiting")
		self.assertEqual(task_view("Blocked", past), "blocked")
		self.assertEqual(task_view("Open", future), "active")
		self.assertEqual(task_view("Done", future), "closed")

	def test_task_reason_registries_store_stable_codes(self):
		self.assertIn("material_shortage", BLOCKER_REASONS)
		self.assertIn("completed", RESOLUTION_REASONS)
		self.assertNotEqual(BLOCKER_REASONS["material_shortage"], "material_shortage")

	def test_owner_reassignment_updates_todo_and_docshare_together(self):
		task = SimpleNamespace(
			doctype="Lumirise Task",
			name="LTASK-TEST",
			title="Reassign safely",
			owner_user="new@example.com",
			supervisor_user="supervisor@example.com",
			hod_user="hod@example.com",
		)
		with (
			patch("frappe.desk.form.assign_to.remove") as remove_assignment,
			patch("frappe.desk.form.assign_to.add") as add_assignment,
			patch.object(frappe.share, "remove") as remove_share,
			patch.object(frappe.share, "add") as add_share,
		):
			synchronize_owner_assignment(task, "old@example.com")

		remove_assignment.assert_called_once_with(
			"Lumirise Task", "LTASK-TEST", "old@example.com", ignore_permissions=True
		)
		remove_share.assert_called_once()
		add_assignment.assert_called_once()
		add_share.assert_called_once_with(
			"Lumirise Task",
			"LTASK-TEST",
			"new@example.com",
			write=1,
			flags={"ignore_share_permission": True},
		)

	def test_post_migration_backfill_is_idempotent(self):
		self.assertEqual(build_backfill_plan(), [])
		self.assertEqual(pending_count(), 0)


class TestPhaseZeroEndpointBoundaries(IntegrationTestCase):
	def test_stock_posting_requires_native_create_and_submit_permissions(self):
		with patch("lumirise_custom.action_permissions.frappe.has_permission") as has_permission:
			require_stock_entry_permissions(submit=True)
		has_permission.assert_has_calls(
			[
				call("Stock Entry", "create", throw=True),
				call("Stock Entry", "submit", throw=True),
			]
		)

	def test_bom_request_maker_cannot_approve_their_own_request(self):
		doc = SimpleNamespace(owner=frappe.session.user, db_set=Mock())
		with (
			patch.object(bom_change_request, "_load", return_value=doc),
			patch.object(bom_change_request, "_has_role", return_value=True),
			self.assertRaises(frappe.PermissionError),
		):
			bom_change_request.approve_change("BCR-TEST")
		doc.db_set.assert_not_called()
