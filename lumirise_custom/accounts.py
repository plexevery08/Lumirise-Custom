"""Accounts automation for the Lumirise build.

Auto Debit Note for rejected purchase qty (Ajay review 2026-06-14,
00:36:23-00:41:20): when the purchase bill is entered for the vendor's full
invoiced quantity, the system must AUTOMATICALLY raise a Debit Note for the
rejected quantity -- left in DRAFT for user approval -- so a forgotten rejection
never turns into an overpayment. "System should automatically raise the debit
note... the debit note should be asked for an approval."

Design notes
------------
* The rejected qty is read from the Purchase Receipt(s) the invoice was made from
  (PR Item.rejected_qty, populated by chain.make_grn from the IQC). The physical
  rejected stock sits in the RM Rejection warehouse (routed there at GRN time).
* This debit note carries the stock back out of the RM Rejection warehouse:
  update_stock = 1 with each return line's warehouse set to the configured
  rejection warehouse. So on submit it BOTH nets the payable down AND clears the
  rejected units from inventory. If no rejection warehouse is configured, it falls
  back to a FINANCIAL-only note (update_stock = 0) rather than breaking the bill.
* The bill is expected to be entered for the vendor's full invoiced (received) qty
  -- that is Lumirise's documented practice. The draft + mandatory approval is the
  safety net if that assumption does not hold for a given bill.
* Anything here is wrapped so a failure can NEVER roll back the legitimate invoice.
"""

import frappe
from frappe.utils import flt


def auto_debit_note_for_rejections(doc, method=None):
	"""Purchase Invoice on_submit -> draft a Debit Note for any rejected qty traced
	back through the linked Purchase Receipt(s). Fail-safe: never throws."""
	try:
		_auto_debit_note(doc)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Auto Debit Note failed")


def _auto_debit_note(doc):
	# Only original purchase bills; skip the debit notes themselves.
	if getattr(doc, "is_return", 0):
		return

	# already drafted one for this invoice?
	if frappe.db.exists("Purchase Invoice", {"return_against": doc.name, "is_return": 1}):
		return

	# Collect rejected qty per invoice line via the PR it was billed from.
	rejected = []  # (item_code, qty, rate)
	total_rej = 0.0
	for it in doc.items:
		pr_rej = 0.0
		if it.get("pr_detail"):
			pr_rej = flt(frappe.db.get_value("Purchase Receipt Item", it.pr_detail, "rejected_qty"))
		elif it.get("purchase_receipt"):
			pr_rej = flt(frappe.db.get_value(
				"Purchase Receipt Item",
				{"parent": it.purchase_receipt, "item_code": it.item_code},
				"rejected_qty"))
		if pr_rej <= 0:
			continue
		# Cannot return more than was billed on this line.
		dn_qty = min(pr_rej, flt(it.qty))
		if dn_qty <= 0:
			continue
		rejected.append((it.item_code, dn_qty, flt(it.rate)))
		total_rej += dn_qty

	if total_rej <= 0:
		return

	# Pull the rejected stock back out of the RM Rejection warehouse on submit.
	from lumirise_custom import defaults as config
	rej_wh = config.rejection_warehouse(required=False)
	do_stock = 1 if rej_wh else 0

	dn = frappe.new_doc("Purchase Invoice")
	dn.supplier = doc.supplier
	dn.company = doc.company
	dn.is_return = 1
	dn.return_against = doc.name
	dn.update_stock = do_stock
	if rej_wh:
		dn.set_warehouse = rej_wh
	dn.set_posting_time = 1
	dn.posting_date = doc.posting_date
	dn.remarks = (
		f"Auto-generated Debit Note for rejected qty against {doc.name}. "
		f"PENDING APPROVAL — review and submit to "
		+ (f"net the payable and clear the rejected stock from {rej_wh}."
		   if rej_wh else "net the payable.")
	)
	for item_code, qty, rate in rejected:
		row = {
			"item_code": item_code,
			"qty": -abs(qty),      # return = negative qty
			"rate": rate,
		}
		if rej_wh:
			row["warehouse"] = rej_wh   # stock leaves the RM Rejection store
		dn.append("items", row)
	dn.insert(ignore_permissions=True)   # stays in DRAFT for approval

	# Task the Accounts/Purchase team to review & approve the debit note.
	try:
		from lumirise_custom.task_engine import create_task
		create_task(
			title=f"Approve auto Debit Note {dn.name} (rejection on bill {doc.name})",
			department="Accounts",
			task_type="Handoff",
			priority="High",
			reference_doctype="Purchase Invoice",
			reference_name=dn.name,
			description=(
				f"Bill {doc.name} ({doc.supplier}) had rejected qty at IQC/GRN. "
				f"A Debit Note {dn.name} for {total_rej:g} unit(s) was auto-drafted"
				+ (f" (Update Stock ON — submitting it removes the rejected units "
				   f"from {rej_wh})." if rej_wh else ".")
				+ " Verify and submit it so the vendor is debited for the rejection."
			),
			source_event="auto_debit_note",
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Auto Debit Note task failed")

	frappe.msgprint(
		f"Auto Debit Note <b>{dn.name}</b> drafted for rejected qty ({total_rej:g}). "
		+ (f"Update Stock is ON ({rej_wh}) — submitting it debits the vendor and "
		   f"clears the rejected stock. "
		   if rej_wh else "It is financial-only (no rejection warehouse configured). ")
		+ "It is pending approval — open and submit it.",
		title="Debit Note raised (approval required)", indicator="orange")
