import frappe
from frappe.tests import IntegrationTestCase

from lumirise_custom.setup.workspaces import WORKSPACES


class TestLumiriseWorkspaces(IntegrationTestCase):
	def test_department_workspaces_are_installed_and_role_gated(self):
		for spec in WORKSPACES:
			self.assertTrue(frappe.db.exists("Workspace", spec["name"]), spec["name"])
			workspace = frappe.get_doc("Workspace", spec["name"])
			self.assertEqual(workspace.module, "Lumirise Custom")
			self.assertEqual(workspace.is_hidden, 0)
			if spec["name"] == "Lumirise Desk":
				self.assertFalse(workspace.roles)
			else:
				self.assertTrue(workspace.roles, spec["name"])

	def test_department_sidebar_contains_every_managed_workspace(self):
		self.assertTrue(frappe.db.exists("Workspace Sidebar", "Lumirise Desk"))
		sidebar = frappe.get_doc("Workspace Sidebar", "Lumirise Desk")
		targets = {item.link_to for item in sidebar.items if item.link_type == "Workspace"}
		self.assertEqual(targets, {spec["name"] for spec in WORKSPACES})

		icon = frappe.get_doc("Desktop Icon", "Lumirise Desk")
		self.assertEqual(icon.link_type, "Workspace Sidebar")
		self.assertEqual(icon.link_to, "Lumirise Desk")
		self.assertEqual(icon.sidebar, "Lumirise Desk")

	def test_workspace_shortcuts_only_target_installed_records(self):
		for spec in WORKSPACES:
			workspace = frappe.get_doc("Workspace", spec["name"])
			self.assertTrue(workspace.number_cards, spec["name"])
			self.assertTrue(workspace.charts, spec["name"])
			for shortcut in workspace.shortcuts:
				if shortcut.type == "DocType":
					self.assertTrue(frappe.db.exists("DocType", shortcut.link_to), shortcut.link_to)
				elif shortcut.type == "Report":
					self.assertTrue(frappe.db.exists("Report", shortcut.link_to), shortcut.link_to)

	def test_common_home_contains_operations_and_governance(self):
		workspace = frappe.get_doc("Workspace", "Lumirise Desk")
		targets = {shortcut.link_to for shortcut in workspace.shortcuts}
		for target in (
			"Lumirise Operations Settings",
			"System Settings",
			"Workflow",
			"Workflow State",
			"User Permission",
			"Notification",
		):
			if frappe.db.exists("DocType", target):
				self.assertIn(target, targets)
