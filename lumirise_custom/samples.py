"""IQC Pre-GRN Sample Accountability (change-list 10.1).

Pre-GRN the inbound lot is NOT owned (see iqc.py: "goods on the dock, not owned"),
so a sample drawn for testing can only be a *log* — there is no stock to move yet.
This module makes the sample accountable without corrupting the ledger:

  1. issue_sample   (pre-GRN)  -> append a custody row on the IQC (item, qty, who,
                                  when). NO stock entry — goods not owned yet.
  2. GRN posts                 -> the accepted qty lands in the RM Store. We then
     (realise_samples_to_lab)    move each outstanding sample RM Store -> IQC Lab
                                  (Material Transfer) so the lab honestly holds it.
                                  Fail-safe: never blocks the GRN.
  3. return_sample             -> IQC Lab -> disposition (the two the client named,
                                  plus scrap):
       Returned Intact          -> IQC Lab -> RM Store
       Built into Finished Unit  -> IQC Lab -> Production FG Store
       Scrapped                  -> Material Issue out of IQC Lab (write-off)

No double count: the GRN receives the accepted qty into RM exactly once; the sample
merely shuttles RM -> Lab -> (RM / FG / out). The lab realisation is idempotent and
also runs lazily inside return_sample, so a return still works even if the GRN-time
hook was skipped (e.g. IQC Lab configured after the GRN posted).

Child rows are inserted / updated at the DB layer (direct child insert +
frappe.db.set_value) so the flow works whether the parent IQC is still a draft
(sample drawn during Testing) or already submitted (Passed, awaiting GRN) — the
submit lock never gets in the way.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from lumirise_custom import defaults as config

# --- sample row status (single source of truth) -----------------------------
ISSUED = "Issued"        # logged pre-GRN, no stock yet
IN_LAB = "In Lab"        # GRN posted, sample transferred RM Store -> IQC Lab
RETURNED = "Returned"    # dispositioned back out of the lab

DISPOSITIONS = ("Returned Intact", "Built into Finished Unit", "Scrapped")

MOVED_TO_RM = "Moved to RM"  # IQC status once the GRN has posted


# --- helpers ----------------------------------------------------------------
def _load_iqc(docname):
	return frappe.get_doc("IQC", docname)


def _sample_row(iqc, row_name):
	for r in iqc.sample_items:
		if r.name == row_name:
			return r
	frappe.throw(_("Sample row not found on {0}.").format(iqc.name))


def _make_sample_stock_entry(iqc, row, purpose, from_wh, to_wh, note):
	"""Build + submit a plain (non-Work-Order) Stock Entry for one sample row.
	`purpose` is a standard Stock Entry purpose — 'Material Transfer' (Lab <-> store)
	or 'Material Issue' (scrap write-off). Standard stock_entry_type is used on
	purpose, so these entries never collide with the Focus-named custom types that
	drive the production task-engine router."""
	se = frappe.new_doc("Stock Entry")
	se.purpose = purpose
	se.stock_entry_type = purpose
	se.company = config.get_company(iqc)
	if from_wh:
		se.from_warehouse = from_wh
	if to_wh:
		se.to_warehouse = to_wh
	se.append("items", {
		"item_code": row.item_code,
		"qty": flt(row.sample_qty),
		"uom": row.uom or config.item_uom(row.item_code),
		"s_warehouse": from_wh,
		"t_warehouse": to_wh,
	})
	se.flags.ignore_permissions = True
	se.insert(ignore_permissions=True)
	se.submit()
	se.add_comment("Comment", _("IQC {0} — {1} (sample {2})").format(iqc.name, note, row.item_code))
	return se


def _ensure_in_lab(iqc, row):
	"""Make sure the sample physically held in the lab is reflected in the ledger.
	Moves RM Store -> IQC Lab if the row is still just a pre-GRN log. Requires the
	GRN to have posted (goods owned). Idempotent — a no-op once In Lab."""
	if row.status == IN_LAB:
		return
	if row.status == RETURNED:
		frappe.throw(_("This sample has already been returned / dispositioned."))
	if iqc.status != MOVED_TO_RM:
		frappe.throw(_(
			"Post the GRN first — the sample's stock is not owned until the accepted "
			"qty lands in the RM Store."))
	rm = config.rm_warehouse()
	lab = config.iqc_lab_warehouse()
	se = _make_sample_stock_entry(iqc, row, "Material Transfer", rm, lab, "received into lab")
	frappe.db.set_value("IQC Sample", row.name, {"status": IN_LAB, "stock_entry": se.name})
	row.status = IN_LAB
	row.stock_entry = se.name


# --- 1. issue (pre-GRN, no stock) -------------------------------------------
@frappe.whitelist()
def issue_sample(docname, item_code, sample_qty, taken_by, remarks=None):
	"""Record a sample drawn from the inbound lot for testing. Pure custody log —
	NO stock entry, because pre-GRN the goods are not yet owned. Works on a draft
	IQC (sample drawn during Testing) or a submitted one (Passed, awaiting GRN)."""
	frappe.has_permission("IQC", "write", docname, throw=True)
	qty = flt(sample_qty)
	if qty <= 0:
		frappe.throw(_("Sample qty must be greater than zero."))
	if not taken_by:
		frappe.throw(_("Record who is taking the sample (Taken By)."))
	iqc = _load_iqc(docname)
	if iqc.docstatus == 2:
		frappe.throw(_("Cannot issue a sample against a cancelled IQC."))
	if iqc.status in (MOVED_TO_RM, "Rejected"):
		frappe.throw(_("Samples are drawn pre-GRN — this IQC is already {0}.").format(iqc.status))
	if item_code not in {r.item_code for r in iqc.items}:
		frappe.throw(_("{0} is not on this IQC's item list.").format(item_code))

	# Direct child insert so we don't fight the parent submit lock.
	next_idx = (max([r.idx for r in iqc.sample_items], default=0)) + 1
	row = frappe.get_doc({
		"doctype": "IQC Sample",
		"parent": iqc.name,
		"parenttype": "IQC",
		"parentfield": "sample_items",
		"idx": next_idx,
		"item_code": item_code,
		"item_name": frappe.db.get_value("Item", item_code, "item_name"),
		"sample_qty": qty,
		"uom": config.item_uom(item_code),
		"taken_by": taken_by,
		"issued_on": now_datetime(),
		"status": ISSUED,
		"remarks": remarks,
	})
	row.flags.ignore_permissions = True
	row.insert(ignore_permissions=True)
	return {"row": row.name, "status": ISSUED}


# --- 2. realise to lab (on GRN submit) --------------------------------------
def realise_samples_to_lab(doc, method=None):
	"""GRN submit doc-event: for each outstanding pre-GRN sample on the passed
	IQC(s) for this PO, transfer the sample qty RM Store -> IQC Lab so the lab holds
	it in the ledger now that the goods are owned. Fail-safe — a sample-transfer
	glitch must never roll back the GRN."""
	if doc.get("is_subcontracted"):
		return  # subcontracting service PR — no RM IQC, no samples
	try:
		from lumirise_custom.chain import _grn_pos
		pos = _grn_pos(doc)
	except Exception:
		return
	for po in pos:
		iqc_names = frappe.get_all(
			"IQC", filters={"purchase_order": po, "docstatus": 1}, pluck="name")
		for iqc_name in iqc_names:
			iqc = frappe.get_doc("IQC", iqc_name)
			for row in iqc.sample_items:
				if row.status != ISSUED:
					continue
				try:
					_ensure_in_lab(iqc, row)
				except Exception:
					frappe.log_error(
						frappe.get_traceback(),
						f"IQC sample -> lab failed (IQC {iqc_name}, row {row.name})")


def revert_samples_from_lab(doc, method=None):
	"""GRN cancel doc-event: reverse the RM -> IQC Lab realisation for samples that
	are still In Lab (not yet dispositioned) and re-open them as pre-GRN logs, so a
	re-GRN re-realises them. Fail-safe."""
	if doc.get("is_subcontracted"):
		return
	try:
		from lumirise_custom.chain import _grn_pos
		pos = _grn_pos(doc)
	except Exception:
		return
	for po in pos:
		iqc_names = frappe.get_all(
			"IQC", filters={"purchase_order": po, "docstatus": 1}, pluck="name")
		for iqc_name in iqc_names:
			iqc = frappe.get_doc("IQC", iqc_name)
			for row in iqc.sample_items:
				if row.status == IN_LAB and row.stock_entry:
					try:
						se = frappe.get_doc("Stock Entry", row.stock_entry)
						if se.docstatus == 1:
							se.cancel()
						frappe.db.set_value(
							"IQC Sample", row.name,
							{"status": ISSUED, "stock_entry": None})
					except Exception:
						frappe.log_error(
							frappe.get_traceback(),
							f"IQC sample lab-revert failed (row {row.name})")
				elif row.status == RETURNED:
					frappe.log_error(
						f"GRN {doc.name} cancelled but IQC {iqc_name} sample {row.name} "
						f"was already dispositioned — reverse it manually.",
						"IQC sample: GRN cancelled after disposition")


# --- 3. return / disposition (Lab -> RM / FG / scrap) -----------------------
@frappe.whitelist()
def return_sample(docname, row_name, disposition):
	"""Disposition a sample out of the IQC Lab. Realises lab custody first if the
	GRN-time hook was skipped (lazy), then posts the disposition Stock Entry."""
	frappe.has_permission("IQC", "write", docname, throw=True)
	if disposition not in DISPOSITIONS:
		frappe.throw(_("Choose a valid disposition: {0}.").format(", ".join(DISPOSITIONS)))
	iqc = _load_iqc(docname)
	row = _sample_row(iqc, row_name)
	if row.status == RETURNED:
		frappe.throw(_("This sample has already been returned / dispositioned."))

	_ensure_in_lab(iqc, row)  # RM -> Lab if not there yet (needs GRN posted)

	lab = config.iqc_lab_warehouse()
	if disposition == "Returned Intact":
		se = _make_sample_stock_entry(
			iqc, row, "Material Transfer", lab, config.rm_warehouse(), "returned intact to RM")
	elif disposition == "Built into Finished Unit":
		se = _make_sample_stock_entry(
			iqc, row, "Material Transfer", lab, config.fg_warehouse(), "built into finished unit -> FG")
	else:  # Scrapped
		se = _make_sample_stock_entry(
			iqc, row, "Material Issue", lab, None, "scrapped (write-off)")

	frappe.db.set_value("IQC Sample", row.name, {
		"status": RETURNED,
		"disposition": disposition,
		"returned_on": now_datetime(),
		"stock_entry": se.name,
	})
	return {"stock_entry": se.name, "disposition": disposition}
