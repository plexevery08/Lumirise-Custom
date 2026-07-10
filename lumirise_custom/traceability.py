# Lumirise cross-document traceability.
#
# Goal (Riddhi, 2026-07-07): running the whole flow SO -> SI, EVERY document in the
# chain should show the four order references it belongs to — Sales Order, Indent,
# Work Order, Purchase Order — so anyone opening any doc can trace the full journey.
#
# Design reality: Lumirise runs a make-to-STOCK netting flow (Material Planning nets
# RM demand across SOs into ONE consolidated Indent -> Purchase Plan -> one PO/vendor).
# So the procurement leg is genuinely many-to-many: a PO/Indent can serve several SOs
# and WOs. We therefore store each reference as a read-only comma-string (Small Text),
# NOT a single Link — honest about the set, and consistent with the
# no-reverse-Link / refs-as-Data rule (lumirise-doctype-conventions Rule 1).
#
# The links themselves already exist end-to-end; this module just walks them and
# stamps the four lr_source_* fields. One resolver, one fail-safe validate handler.

import frappe

# The four traceability fields, in display order. Present on every chain doctype
# (created either by setup/traceability_fields.py for standard doctypes, or in the
# JSON of the custom doctypes). stamp() only writes the ones a given doc actually has.
FIELDS = (
	("lr_source_so", "so"),
	("lr_source_indent", "indent"),
	("lr_source_wo", "wo"),
	("lr_source_po", "po"),
)


def _split_refs(value):
	"""A Small Text like 'IND-0001, IND-0002' -> ['IND-0001', 'IND-0002']."""
	return [x.strip() for x in (value or "").split(",") if x.strip()]


def resolve(seed):
	"""Given whatever references a document knows directly (the seed), return the
	full {so, indent, wo, po} reference sets by walking the existing links.

	seed is a dict with any of the keys 'so' / 'po' / 'wo' / 'indent' -> iterable of
	docnames the document references DIRECTLY. We seed the result with those (so a doc
	always shows at least what it points at), normalise everything down to the Sales
	Order set, then expand back out to the full four sets.
	"""
	so = set(seed.get("so") or [])
	po = set(seed.get("po") or [])
	wo = set(seed.get("wo") or [])
	indent = set(seed.get("indent") or [])

	# --- normalise the seed down to a Sales Order set -----------------------------
	# PO -> its Indents (via the lr_indent_refs comma-string on the PO).
	for p in list(po):
		refs = frappe.db.get_value("Purchase Order", p, "lr_indent_refs")
		for iname in _split_refs(refs):
			indent.add(iname)
	# Indent -> its Sales Order.
	for iname in list(indent):
		so_name = frappe.db.get_value("Indent", iname, "source_sales_order")
		if so_name:
			so.add(so_name)
	# Work Order -> its Sales Order.
	for w in list(wo):
		so_name = frappe.db.get_value("Work Order", w, "sales_order")
		if so_name:
			so.add(so_name)

	# --- expand the full Sales Order set back out to all four sets -----------------
	if so:
		sos = list(so)
		for i in frappe.get_all("Indent", {"source_sales_order": ["in", sos]}, pluck="name"):
			indent.add(i)
		for w in frappe.get_all("Work Order", {"sales_order": ["in", sos]}, pluck="name"):
			wo.add(w)
		# PO set: any submitted/draft PO whose lr_indent_refs mentions one of our indents.
		for iname in list(indent):
			for p in frappe.get_all(
				"Purchase Order",
				{"lr_indent_refs": ["like", f"%{iname}%"], "docstatus": ["!=", 2]},
				pluck="name",
			):
				po.add(p)

	# Never surface a CANCELLED document (docstatus 2) as a reference. Cancelled
	# links may still be used above to locate the live chain, but they must not be
	# displayed. Single final pass covers seeds and expansions uniformly.
	return {
		"so": _drop_cancelled("Sales Order", so),
		"indent": _drop_cancelled("Indent", indent),
		"wo": _drop_cancelled("Work Order", wo),
		"po": _drop_cancelled("Purchase Order", po),
	}


def _drop_cancelled(doctype, names):
	"""Return sorted names for the given doctype, excluding cancelled (docstatus 2)
	and any that no longer exist."""
	if not names:
		return []
	live = frappe.get_all(
		doctype,
		{"name": ["in", list(names)], "docstatus": ["!=", 2]},
		pluck="name",
	)
	return sorted(live)


def _seed_for(doc):
	"""What references does THIS document point at directly? Returns a seed dict, or
	None if the doctype is not part of the traceable chain."""
	dt = doc.doctype

	if dt == "Sales Order":
		return {"so": [doc.name]}
	if dt == "Work Order":
		return {"wo": [doc.name], "so": [doc.sales_order] if doc.get("sales_order") else []}
	if dt == "Indent":
		return {"indent": [doc.name],
		        "so": [doc.source_sales_order] if doc.get("source_sales_order") else []}
	if dt == "Purchase Order":
		return {"po": [doc.name]}
	if dt in ("Vendor PDI", "Inbound Logistics", "IQC"):
		return {"po": [doc.purchase_order] if doc.get("purchase_order") else []}
	if dt in ("Purchase Receipt", "Purchase Invoice"):
		return {"po": [r.purchase_order for r in doc.items if r.get("purchase_order")]}
	if dt == "Customer PDI":
		return {"so": [doc.sales_order] if doc.get("sales_order") else []}
	if dt == "Delivery Note":
		return {"so": [r.against_sales_order for r in doc.items if r.get("against_sales_order")]}
	if dt == "Sales Invoice":
		return {"so": [r.sales_order for r in doc.items if r.get("sales_order")]}
	if dt in ("Stock Entry", "Material Receipt"):
		return {"wo": [doc.work_order] if doc.get("work_order") else []}
	return None


def _write(doc, refs):
	"""Write the resolved reference sets onto whichever lr_source_* fields the doc has."""
	for fieldname, key in FIELDS:
		if doc.meta.has_field(fieldname):
			doc.set(fieldname, ", ".join(refs[key]))


def stamp(doc, method=None):
	"""doc_event (validate) handler: fill the traceability panel on any chain doc.

	Fail-safe — a traceability glitch must NEVER roll back the business transaction
	(lumirise-doctype-conventions Rule 4)."""
	try:
		seed = _seed_for(doc)
		if seed is None:
			return
		_write(doc, resolve(seed))
	except Exception:
		frappe.log_error(frappe.get_traceback(), "lumirise traceability.stamp")


def restamp(doctype, name):
	"""Recompute + persist the panel on an ALREADY-SAVED (often submitted) doc, via
	db_set. Used when a later step creates the links a root doc should now show —
	e.g. Material Planning creating the WO/Indent for a submitted Sales Order.
	Fail-safe."""
	try:
		if not frappe.db.exists(doctype, name):
			return
		doc = frappe.get_doc(doctype, name)
		seed = _seed_for(doc)
		if seed is None:
			return
		refs = resolve(seed)
		for fieldname, key in FIELDS:
			if doc.meta.has_field(fieldname):
				frappe.db.set_value(doctype, name, fieldname, ", ".join(refs[key]),
				                    update_modified=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "lumirise traceability.restamp")
