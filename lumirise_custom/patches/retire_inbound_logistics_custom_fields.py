"""Retire the Inbound Logistics Custom Field overlay (2026-08-11).

The 60 material-inward fields used to be Custom Fields injected by
``setup/inward_process.py``. Their placement was decided by ``insert_after``,
which forced the whole block to render as one flat run of 56 stacked fields and
made the form impossible to organise. They now live in ``inbound_logistics.json``
with a proper tab / section / column layout, so the overlay must go — otherwise
every field would exist twice in the merged meta.

Runs in post_model_sync, i.e. after the doctype JSON has been imported, so the
"is it in the JSON yet?" guard inside ``retire_inbound_custom_fields`` passes.

Data safety: deleting a Custom Field does not drop its database column, and the
JSON reuses the identical fieldnames, so values on existing records are kept.
"""

import frappe

from lumirise_custom.setup.inward_process import retire_inbound_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Inbound Logistics"):
		return

	retired = retire_inbound_custom_fields()
	if retired:
		frappe.db.commit()
