# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Lumirise Task = one operational to-do / Kanban card. Created automatically by
# the task engine (task_engine.py) on every cross-department handoff, defect,
# rejection, missed deadline or error so the work that used to live in Bitrix /
# WhatsApp becomes a tracked, assignable, escalatable ERP record.

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class LumiriseTask(Document):
	def validate(self):
		# Stamp completion time when the card reaches a terminal column.
		if self.status in ("Done", "Cancelled"):
			if not self.completed_on:
				self.completed_on = now_datetime()
		else:
			self.completed_on = None
