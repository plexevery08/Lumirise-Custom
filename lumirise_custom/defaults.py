"""Dynamic configuration resolver.

Single place that resolves the operational warehouses / company / UOM the engine
needs — read from the "Lumirise Operations Settings" single doc (or derived
dynamically), never hard-coded in business logic. If something the flow needs is
not configured, we raise a clear, actionable error instead of guessing.
"""

import frappe
from frappe import _


def _settings():
	return frappe.get_cached_doc("Lumirise Operations Settings")


def get_company(doc=None):
	"""Company from the document, else the configured default, else the system
	default company — resolved dynamically, never a literal."""
	if doc is not None and getattr(doc, "company", None):
		return doc.company
	configured = _settings().company
	if configured:
		return configured
	import erpnext

	return erpnext.get_default_company()


def _warehouse(field, label, required=True):
	value = _settings().get(field)
	if not value and required:
		frappe.throw(
			_("Configure the <b>{0}</b> in Lumirise Operations Settings before running this step.").format(label),
			title=_("Operations Settings Missing"),
		)
	return value


def rm_warehouse():
	return _warehouse("rm_warehouse", "Raw Material Store")


def shop_floor_warehouse():
	return _warehouse("shop_floor_warehouse", "Shop Floor")


def fg_warehouse():
	"""Production FG store — where Manufacture first lands finished goods."""
	return _warehouse("fg_warehouse", "Production FG Store")


# Alias for readability at call sites that mean "Production FG" explicitly.
def production_fg_warehouse():
	return fg_warehouse()


def dispatch_fg_warehouse():
	return _warehouse("dispatch_fg_warehouse", "Dispatch FG Store")


def pdi_warehouse():
	return _warehouse("pdi_warehouse", "Customer PDI Store")


def iqc_lab_warehouse():
	"""Sample-custody warehouse the IQC lab draws pre-GRN samples into (10.1)."""
	return _warehouse("iqc_lab_warehouse", "IQC Lab")


def wip_warehouse():
	return _warehouse("wip_warehouse", "Default Line WIP")


def rejection_warehouse(required=False):
	return _warehouse("rejection_warehouse", "Rejection Store", required=required)


def receiving_warehouse():
	return _warehouse("receiving_warehouse", "Receiving / Staging", required=False)


def production_lines(active_only=True):
	"""List the configured per-line warehouses (Settings → Production Lines).

	Returns a list of dicts: {"line_name", "line_warehouse"}. Empty if none set —
	callers fall back to the Default Line WIP warehouse."""
	rows = _settings().production_lines or []
	return [
		{"line_name": r.line_name, "line_warehouse": r.line_warehouse}
		for r in rows
		if r.line_warehouse and (not active_only or r.is_active)
	]


def is_valid_line(warehouse):
	"""True if the warehouse is one of the configured production lines."""
	return any(l["line_warehouse"] == warehouse for l in production_lines())


def item_uom(item_code):
	"""Stock UOM of the item — dynamic, never a hard-coded 'Nos'."""
	return frappe.db.get_value("Item", item_code, "stock_uom")


@frappe.whitelist()
def form_warehouse_defaults():
	"""Resolved default warehouses for new-form auto-fill (Customer PDI source/PDI/
	rejection, Delivery Note dispatch source). Client scripts call this on a NEW doc
	so the warehouse shows *before* save — the dynamic, "nothing static" way to seed
	a form default (Rule 3: never a hard-coded Property Setter default). Each lookup
	is fail-safe: an unconfigured warehouse returns null rather than throwing and
	breaking form load."""

	def _safe(fn):
		try:
			return fn()
		except Exception:
			return None

	return {
		"dispatch_fg": _safe(dispatch_fg_warehouse),
		"production_fg": _safe(fg_warehouse),
		"pdi": _safe(pdi_warehouse),
		"rejection": _safe(lambda: rejection_warehouse(required=False)),
	}


def flag(field, default=True):
	value = _settings().get(field)
	return bool(value) if value is not None else default


def assert_destructive_seeder_allowed(action="this destructive seeder"):
	"""HARD kill-switch for ANY seeder/cleanup that bulk-deletes or mass-creates docs
	(smoke_test / sales_smoke_test / full_flow_all_forms run() + cleanup(), and the
	health-check synthetic tier). Refuses on EVERY site unless it is an explicitly
	marked throwaway:

	  1. NEVER on the production site — site_config `is_production_site`, or the
	     configured Operations Settings `production_site_name`; and
	  2. ONLY when site_config.json carries `allow_destructive_seeders: 1` — a dev-only
	     file that no desk user, scheduler, reseed, or settings toggle can change.

	This is the guard between a "delete every transaction" routine and real client data,
	independent of HOW it is invoked (bench execute, scheduler, health tier). It throws
	(does nothing) on any bench that isn't a deliberately-armed throwaway.
	(2026-07-13: added after the unguarded synthetic tier twice wiped real dev data.)
	"""
	site = getattr(frappe.local, "site", None)
	prod_name = (frappe.db.get_single_value("Lumirise Operations Settings", "production_site_name") or "").strip()
	if frappe.conf.get("is_production_site") or (prod_name and site == prod_name):
		frappe.throw(f"REFUSED — {action} must NEVER run on the production site ({site}).")
	if not frappe.conf.get("allow_destructive_seeders"):
		frappe.throw(
			f"REFUSED — {action} bulk-deletes/creates data and is DISABLED on this site "
			f"({site}); it can wipe real transactions. To run it on a THROWAWAY test site "
			f"only, first set 'allow_destructive_seeders': 1 in that site's site_config.json. "
			f"Never set it on a bench that holds real data."
		)
