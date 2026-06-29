# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Line Daily Closing = the end-of-day per-line reconciliation that gives EOD stock
# a named owner and closes it. opening WIP + received - produced - rejected -
# closing WIP must net to zero; a non-zero variance is the daily leak surfacing
# immediately, and on submit it escalates a Stock-Mismatch task to Production.

import frappe
from frappe.model.document import Document
from frappe.utils import flt

TOLERANCE = 0.001


class LineDailyClosing(Document):
	def validate(self):
		self.variance = (
			flt(self.opening_wip)
			+ flt(self.material_received)
			- flt(self.produced_fg)
			- flt(self.rejected_qty)
			- flt(self.closing_wip)
		)
		self.is_balanced = 1 if abs(self.variance) <= TOLERANCE else 0

	def on_submit(self):
		if not self.is_balanced:
			self._raise_variance_alert()

	def _raise_variance_alert(self):
		from lumirise_custom.task_engine import create_task

		create_task(
			title=f"Line {self.production_line}: EOD stock variance {flt(self.variance):g} on {self.closing_date}",
			department="Production",
			task_type="Stock Mismatch",
			priority="High",
			reference_doctype=self.doctype,
			reference_name=self.name,
			description=(
				f"Line {self.production_line} did not balance on {self.closing_date}: "
				f"opening {flt(self.opening_wip):g} + received {flt(self.material_received):g} "
				f"- produced {flt(self.produced_fg):g} - rejected {flt(self.rejected_qty):g} "
				f"- closing {flt(self.closing_wip):g} = variance {flt(self.variance):g}. "
				f"Locate the missing/extra units before the next day's run."
			),
			source_event="line_daily_closing_variance",
		)
