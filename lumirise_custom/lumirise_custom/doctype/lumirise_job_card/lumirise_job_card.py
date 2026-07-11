# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Lumirise Job Card = a per-line, per-day production target with a miss-alert.
# Open it in the morning with a target; enter produced qty at close (or fetch it
# from the Work Order). On submit it computes variance and, if the line fell
# short, auto-escalates a task to Production -- the "missed-target escalation"
# the floor does not have today.

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class LumiriseJobCard(Document):
	def validate(self):
		# Material-driven daily target (client rule, 2026-07-08): Carry Fwd + New RM
		# Issued. The supervisor is judged on what the line actually received, not the
		# plan — the plan-vs-material gap is Planning/Stores'. Falls back to a manually
		# entered target_qty when no material figures are present.
		material_target = flt(self.carry_fwd_qty) + flt(self.new_rm_issued)
		if material_target > 0:
			self.target_qty = material_target
		self.variance = flt(self.produced_qty) - flt(self.target_qty)
		self.achievement_pct = (
			flt(self.produced_qty) / flt(self.target_qty) * 100.0 if flt(self.target_qty) else 0
		)
		if flt(self.produced_qty) <= 0:
			self.status = "Open"
		elif self.variance < 0:
			self.status = "Missed"
		else:
			self.status = "Met"

	def on_submit(self):
		if self.status == "Missed":
			self._raise_miss_alert()

	def _raise_miss_alert(self):
		from lumirise_custom.task_engine import create_task

		short = abs(flt(self.variance))
		line = self.production_line
		create_task(
			title=f"Line {line}: missed daily target by {short:g} on {self.production_date}",
			department="Production",
			task_type="Missed Deadline",
			priority="High",
			reference_doctype=self.doctype,
			reference_name=self.name,
			description=(
				f"Production Line {line} produced {flt(self.produced_qty):g} against a "
				f"target of {flt(self.target_qty):g} on {self.production_date} "
				f"(shortfall {short:g}). Investigate and re-plan."
			),
			# The miss is already late, so date the task to the production day. Without a
			# due_date, task_engine.escalate_overdue_tasks (which filters due_date is-set
			# AND < today) can never escalate this to the Production HOD.
			due_date=self.production_date,
			source_event="job_card_missed_target",
		)


@frappe.whitelist()
def fetch_produced_from_wo(docname):
	"""Pull produced qty from the linked Work Order (produced_qty) so the
	supervisor does not retype it."""
	frappe.has_permission("Lumirise Job Card", "write", docname, throw=True)
	doc = frappe.get_doc("Lumirise Job Card", docname)
	if not doc.work_order:
		frappe.throw("Link a Work Order first.")
	produced = flt(frappe.db.get_value("Work Order", doc.work_order, "produced_qty"))
	doc.db_set("produced_qty", produced)
	doc.reload()
	doc.validate()
	doc.db_set("variance", doc.variance)
	doc.db_set("status", doc.status)
	return {"produced_qty": produced, "status": doc.status, "variance": doc.variance}
