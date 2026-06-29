# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Lumirise AQL sampling engine.
#
# Replaces the manual IS:2500 table look-up the inspectors do today (a free-text
# "Sampling Plan" field). Given a lot (received / FG qty), it computes:
#   lot size  ->  General Inspection Level I sample-size code letter
#             ->  sample size (how many to inspect)
#             ->  Accept / Reject number for the relevant AQL.
#
# The AQL applied is chosen by defect class (from Lumirise Defect Code):
#   A (Critical) -> AQL 0.10 · B (Major) -> AQL 1.50 · C (Minor) -> AQL 2.50.
#
# IMPORTANT (QA sign-off): the sample-size code-letter mapping and sample sizes
# below are the fixed ISO 2859-1 / IS 2500 Level I values. The Accept (Ac) numbers
# are the standard single-sampling NORMAL values; QA MUST verify them against the
# physical IS:2500 master table (page-3/3 annexure) before relying on them for
# vendor claims. They are kept here, in one obvious place, for exactly that review.

import frappe
from frappe.utils import flt, cint

# Lot-size band -> General Inspection Level I sample-size code letter.
_LETTER_BANDS = [
	(2, 8, "A"), (9, 15, "A"), (16, 25, "B"), (26, 50, "C"), (51, 90, "C"),
	(91, 150, "D"), (151, 280, "E"), (281, 500, "F"), (501, 1200, "G"),
	(1201, 3200, "H"), (3201, 10000, "J"), (10001, 35000, "K"),
	(35001, 150000, "L"), (150001, 500000, "M"), (500001, 10 ** 12, "N"),
]

# Code letter -> sample size (units to inspect).
_LETTER_N = {
	"A": 2, "B": 3, "C": 5, "D": 8, "E": 13, "F": 20, "G": 32, "H": 50,
	"J": 80, "K": 125, "L": 200, "M": 315, "N": 500,
}
_LETTER_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N"]

# Accept number (Re = Ac + 1) by AQL, single sampling, normal. None = "use the
# first sampling plan below the arrow" (i.e. step to the next larger sample size).
_AC = {
	"2.50": {"A": None, "B": None, "C": 0, "D": 0, "E": 1, "F": 1, "G": 2,
	         "H": 3, "J": 5, "K": 7, "L": 10, "M": 14, "N": 21},
	"1.50": {"A": None, "B": None, "C": None, "D": 0, "E": 1, "F": 1, "G": 2,
	         "H": 3, "J": 5, "K": 7, "L": 10, "M": 14, "N": 21},
	"0.10": {"A": None, "B": None, "C": None, "D": None, "E": None, "F": None,
	         "G": None, "H": None, "J": None, "K": 0, "L": 0, "M": 1, "N": 1},
}

_CLASS_AQL = {"A": "0.10", "B": "1.50", "C": "2.50"}


def _letter_for_lot(lot_size):
	lot = cint(lot_size)
	if lot < 2:
		return "A"
	for lo, hi, letter in _LETTER_BANDS:
		if lo <= lot <= hi:
			return letter
	return "N"


def _resolve(letter, aql):
	"""Follow the down-arrow to the first numeric Accept number; return (letter, Ac)."""
	idx = _LETTER_ORDER.index(letter)
	while idx < len(_LETTER_ORDER):
		l = _LETTER_ORDER[idx]
		ac = _AC[aql].get(l)
		if ac is not None:
			return l, ac
		idx += 1
	# fell off the end -> use the largest plan
	return "N", _AC[aql]["N"]


def compute_aql(lot_size, defect_class="C"):
	"""Core engine: lot size + defect class -> sampling plan.
	Returns dict with code_letter, sample_size, aql, accept, reject, inspect_100pct."""
	lot = cint(lot_size)
	aql = _CLASS_AQL.get((defect_class or "C").upper(), "2.50")
	base_letter = _letter_for_lot(lot)
	plan_letter, ac = _resolve(base_letter, aql)
	n = _LETTER_N[plan_letter]
	inspect_100 = n >= lot and lot > 0
	if inspect_100:
		n = lot  # cannot sample more than the lot -> 100% inspection
	return {
		"lot_size": lot,
		"defect_class": (defect_class or "C").upper(),
		"aql": aql,
		"code_letter": base_letter,
		"plan_letter": plan_letter,
		"sample_size": n,
		"accept": ac,
		"reject": ac + 1,
		"inspect_100pct": inspect_100,
	}


def plan_summary(lot_size, defect_class="C"):
	p = compute_aql(lot_size, defect_class)
	tail = " (100% — lot smaller than sample)" if p["inspect_100pct"] else ""
	return (f"Lot {p['lot_size']} · Level I · code {p['plan_letter']} · "
	        f"AQL {p['aql']} (class {p['defect_class']}) · inspect {p['sample_size']}{tail} · "
	        f"Accept ≤{p['accept']}, Reject ≥{p['reject']}")


# --------------------------------------------------------------- IQC / PDI hooks
def _lot_from_iqc(doc):
	return sum(flt(r.received_qty) for r in doc.items) or 0


@frappe.whitelist()
def apply_to_iqc(docname):
	"""Button on IQC: compute the sampling plan for the worst defect class that
	applies to incoming material (default Critical/A so the tightest plan is shown)
	and write it onto the free-text Sampling Plan field. Read-only on the numbers —
	the inspector still enters accepted/rejected qty per line."""
	frappe.has_permission("IQC", "write", docname, throw=True)
	doc = frappe.get_doc("IQC", docname)
	lot = _lot_from_iqc(doc)
	if lot <= 0:
		frappe.throw("Enter the received qty first, then compute the sampling plan.")
	# Show all three class plans so the inspector sees the tightest one to use.
	lines = [plan_summary(lot, c) for c in ("A", "B", "C")]
	summary = " | ".join(lines)
	doc.db_set("sampling_plan", summary)
	return {"sampling_plan": summary, "plans": [compute_aql(lot, c) for c in ("A", "B", "C")]}


@frappe.whitelist()
def aql_for_lot(lot_size, defect_class="C"):
	"""Generic whitelisted entry point (used by Customer PDI and ad-hoc lookups)."""
	return compute_aql(lot_size, defect_class)
