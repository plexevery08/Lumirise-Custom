"""Move the POD (Proof of Delivery) attachment field from Delivery Note to Sales
Invoice.

The field `lr_pod_attachment` used to live on the Delivery Note (fixture
"Delivery Note-lr_pod_attachment"). The fixture now targets Sales Invoice, so the
Sales Invoice copy is (re)created by the normal Custom Field fixture sync. This
patch removes the stale Delivery Note copy, which the additive fixture import will
never delete on its own.

Idempotent: a no-op if the Delivery Note field is already gone.
"""

import frappe


def execute():
	name = "Delivery Note-lr_pod_attachment"
	if frappe.db.exists("Custom Field", name):
		frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype="Delivery Note")
