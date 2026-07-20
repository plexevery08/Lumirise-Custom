"""Purchase Order BOM Reconciliation + per-model price split.

Two buyer pain points from the May-25 discovery call (Rishitha):

  1. BOM tally — for the models on a PO, list the FULL kit (every BOM component)
     and flag which components are MISSING from the indents that fed the PO. Today
     this is a 1-2 hr manual check across 6-7 models.

  2. Split price per model — a shared component (e.g. screws) is bought as ONE
     consolidated qty; show how that qty (and its cost) splits across the models
     that use it, priced from the RM Price Book (the live price source).

Read-only: never mutates the PO. Surfaced in the "BOM Reconciliation" tab on the
Purchase Order form (public/js/purchase_order.js).
"""

import frappe
from frappe.utils import flt

# RM stock store (kept consistent with indent.py / material_planning).
RM_STORE = "Stores - L"


def _indent_names(po):
	refs = (po.get("lr_indent_refs") or "").replace("\n", ",")
	return [n.strip() for n in refs.split(",") if n.strip()]


def _rm_price(item_code, qty=None):
	"""MD-approved RM Price Book rate for the item, from the LATEST approved book that
	prices it. v2 supports multiple vendor / qty-range rows: among the rows matching the
	qty range, pick the Preferred vendor, else the lowest rate.

	Reads base_rate (company currency), NOT the vendor-currency rate -- rows from
	different vendors can be quoted in different currencies, so comparing raw `rate`
	across them would pick the wrong vendor and return a foreign-currency number.

	NOTE: preferred-then-lowest is a deterministic INTERIM rule so costing never picks an
	arbitrary row; the final vendor-selection policy is confirmed at the purchase meeting
	(lumirise-decision-gates). Backward compatible — a single legacy row returns as before.
	"""
	rows = frappe.db.sql(
		"""SELECT i.base_rate AS rate, i.min_qty, i.max_qty, i.preferred
		   FROM `tabRM Price Book Item` i
		   JOIN `tabRM Price Book` p ON p.name = i.parent
		   WHERE i.item_code = %s AND p.docstatus = 1
		     AND p.name = (
		        SELECT p2.name FROM `tabRM Price Book Item` i2
		        JOIN `tabRM Price Book` p2 ON p2.name = i2.parent
		        WHERE i2.item_code = %s AND p2.docstatus = 1
		        ORDER BY p2.modified DESC LIMIT 1)""",
		(item_code, item_code),
		as_dict=True,
	)
	if not rows:
		return 0.0
	q = flt(qty)

	def in_range(r):
		lo, hi = flt(r.min_qty), flt(r.max_qty)
		if q and lo and q < lo:
			return False
		if q and hi and q > hi:
			return False
		return True

	candidates = [r for r in rows if in_range(r)] or rows
	candidates.sort(key=lambda r: (0 if r.preferred else 1, flt(r.rate)))
	return flt(candidates[0].rate)


def _rm_stock(item_code):
	return flt(frappe.db.get_value(
		"Bin", {"item_code": item_code, "warehouse": RM_STORE}, "actual_qty"))


@frappe.whitelist()
def get_bom_reconciliation(po_name):
	"""Build the kit-reconciliation + per-model price-split payload for a PO.
	Reconciles the FULL model BOM against the items present on the source Indents
	(what Planning actually gave). Pure read — no writes."""
	po = frappe.get_doc("Purchase Order", po_name)
	indents = _indent_names(po)

	# --- gather indented qty, the models, and the source sales orders
	indented_qty = {}          # item_code -> total qty across the source indents
	models = {}                # model -> fg order qty
	source_sos = set()
	for name in indents:
		if not frappe.db.exists("Indent", name):
			continue
		ind = frappe.get_doc("Indent", name)
		if ind.get("source_sales_order"):
			source_sos.add(ind.source_sales_order)
		for row in ind.items:
			indented_qty[row.item_code] = indented_qty.get(row.item_code, 0) + flt(row.qty)
			if row.get("model"):
				models.setdefault(row.model, 0.0)
			if row.get("for_sales_order"):
				source_sos.add(row.for_sales_order)

	# model FG qty from the source Sales Orders (scales the BOM kit)
	for so in source_sos:
		if not frappe.db.exists("Sales Order", so):
			continue
		so_doc = frappe.get_doc("Sales Order", so)
		for it in so_doc.items:
			if it.item_code in models:
				models[it.item_code] += flt(it.qty)

	# --- kit reconciliation per model + per-component model weights (for the split)
	kit = []
	comp_model_weight = {}     # component -> {model -> weight}
	for model, fg_qty in models.items():
		bom = frappe.db.get_value("Item", model, "default_bom")
		comps = []
		if bom:
			bom_doc = frappe.get_doc("BOM", bom)
			per = flt(bom_doc.quantity) or 1
			for bi in bom_doc.items:
				required = flt(bi.qty) / per * flt(fg_qty)
				in_ind = flt(indented_qty.get(bi.item_code, 0))
				comps.append({
					"component": bi.item_code,
					"item_name": bi.item_name or bi.item_code,
					"required": required,
					"in_indent": in_ind,
					"in_stock": _rm_stock(bi.item_code),
					"missing": in_ind <= 0,
				})
				# weight uses (fg_qty or 1) so a shared component still splits even
				# when the FG qty is unknown (proportional by BOM usage).
				w = comp_model_weight.setdefault(bi.item_code, {})
				w[model] = w.get(model, 0) + flt(bi.qty) / per * (flt(fg_qty) or 1)
		kit.append({"model": model, "fg_qty": flt(fg_qty), "components": comps})

	# --- per-model price split for the qty actually on the PO (RM Price Book rate)
	split = []
	for poi in po.items:
		weights = comp_model_weight.get(poi.item_code, {})
		rate = _rm_price(poi.item_code)
		total_w = sum(weights.values())
		rows = []
		if total_w > 0:
			for model, w in weights.items():
				alloc = flt(poi.qty) * w / total_w
				rows.append({"model": model, "qty": alloc, "rate": rate, "amount": alloc * rate})
		else:
			rows.append({"model": "(unsplit)", "qty": flt(poi.qty),
			             "rate": rate, "amount": flt(poi.qty) * rate})
		split.append({
			"item_code": poi.item_code,
			"item_name": poi.item_name or poi.item_code,
			"total_qty": flt(poi.qty),
			"rate": rate,
			"total_amount": flt(poi.qty) * rate,
			"rows": rows,
		})

	return {"has_refs": bool(indents), "indents": indents, "kit": kit, "split": split}
