# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Lumirise Task = one operational to-do / Kanban card. Created automatically by
# the task engine (task_engine.py) on every cross-department handoff, defect,
# rejection, missed deadline or error so the work that used to live in Bitrix /
# WhatsApp becomes a tracked, assignable, escalatable ERP record.

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from lumirise_custom.task_contracts import normalize_task, synchronize_owner_assignment


class LumiriseTask(Document):
	def validate(self):
		normalize_task(self)

		# Stamp completion time when the card reaches a terminal column.
		if self.status in ("Done", "Cancelled"):
			if not self.completed_on:
				self.completed_on = now_datetime()
		else:
			self.completed_on = None

	def on_update(self):
		before = self.get_doc_before_save()
		if before and before.owner_user != self.owner_user:
			synchronize_owner_assignment(self, before.owner_user)
