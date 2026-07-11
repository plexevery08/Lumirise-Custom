# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

"""Lumirise daily self-test / health-check.

A self-hosted "is the whole machine working?" probe that runs every day from the
bench scheduler and answers, in plain English, *what* broke and *how to fix it*.

Two tiers
---------
* READ-ONLY tier  — non-destructive integrity / config assertions. Safe on the
  LIVE cloud site. Runs on EVERY site, every day.
* SYNTHETIC tier  — drives a real order-to-cash + costing chain through the
  existing demo smoke tests (creates and then cleans up test documents). Runs
  ONLY on a test site, behind a triple fail-closed gate, so it can never touch
  production data.

Delivery is IN-ERP ONLY: every run writes a `Health Check Run` doc (header +
per-check results with remediations) and pushes ONE rolled-up desk notification
(Notification Log) per recipient — a green heartbeat when healthy, a red punch
list when not. No email / Slack / webhook.

FAIL-SAFE by design: a broken check becomes a `fail` row, never an aborted run;
the run always produces a digest. Follows the app's established try/except ->
frappe.log_error pattern (see task_engine.escalate_overdue_tasks).

Run (scheduler):  lumirise_custom.health_check.run_daily_health_check
Run (manual CLI): bench --site <site> execute lumirise_custom.health_check.run_daily_health_check
Trigger (UI/API): lumirise_custom.health_check.trigger_health_check
"""

import frappe
from frappe.utils import add_to_date, cint, flt, get_url_to_form, now_datetime

SETTINGS = "Lumirise Operations Settings"

# Stage / category labels grouping the checks in the digest and reports.
COSTING = "Costing"
STATUS = "Status Sync"
GATES = "Quality Gates"
PRODUCTION = "Production"
TASKS = "Tasks"
PERMISSIONS = "Permissions"
WAREHOUSES = "Warehouses"
SCHEDULER = "Scheduler"
DRIFT = "Drift"
STOCK = "Stock"
SYNTHETIC = "Synthetic"


# ---------------------------------------------------------------------------
# Registry + fail-safe runner
# ---------------------------------------------------------------------------

_READONLY_CHECKS = []  # list[(key, title, stage, fn)]


def readonly_check(key, title, stage):
	"""Register a non-destructive check. The function returns a dict (or a
	(status, detail, remediation, evidence) tuple); _run_one normalises it."""

	def deco(fn):
		_READONLY_CHECKS.append((key, title, stage, fn))
		return fn

	return deco


def _result(key, title, stage, status, detail="", remediation="", evidence=""):
	return {
		"key": key,
		"title": title,
		"stage": stage,
		"status": status,
		"detail": detail or "",
		"remediation": remediation or "",
		"evidence": evidence or "",
	}


def _run_one(key, title, stage, fn):
	"""Execute one check fail-safe. An exception means the check itself is broken
	— that is a FAIL, never an aborted run."""
	try:
		r = fn()
		if isinstance(r, dict):
			# Checks return _result("", "", "", ...) and rely on the registry for
			# their identity — fill any blanks (setdefault would keep the "").
			r["key"] = r.get("key") or key
			r["title"] = r.get("title") or title
			r["stage"] = r.get("stage") or stage
			r.setdefault("status", "pass")
			r.setdefault("detail", "")
			r.setdefault("remediation", "")
			r.setdefault("evidence", "")
			return r
		status, detail, remediation, evidence = (list(r) + ["", "", ""])[:4]
		return _result(key, title, stage, status, detail, remediation, evidence)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Health Check broke: {key}")
		return _result(
			key,
			title,
			stage,
			"fail",
			detail="The check itself raised an exception and could not be evaluated.",
			remediation="Open Error Log (filter title 'Health Check broke') for the traceback.",
		)


def _counts(results):
	c = {"pass": 0, "warn": 0, "fail": 0}
	for r in results:
		c[r["status"]] = c.get(r["status"], 0) + 1
	return c


def _overall(counts):
	if counts["fail"]:
		return "Red"
	if counts["warn"]:
		return "Amber"
	return "Green"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_daily_health_check(trigger="scheduled"):
	"""Entry point — wired into scheduler_events['daily'] and the manual trigger.

	Runs every read-only check; runs the synthetic tier only when the gate allows
	it; persists one Health Check Run; pushes the in-ERP digest. A single commit
	at the very end keeps the synthetic smoke tests' savepoints intact."""
	results = []
	for key, title, stage, fn in _READONLY_CHECKS:
		results.append(_run_one(key, title, stage, fn))

	synthetic_ran = False
	if _synthetic_allowed():
		synthetic_ran = True
		try:
			results.extend(_run_synthetic_tier())
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Health Check: synthetic tier crashed")
			results.append(
				_result(
					"synthetic_tier",
					"Synthetic tier executed",
					SYNTHETIC,
					"fail",
					detail="The synthetic tier crashed before producing results.",
					remediation="See Error Log; check the demo smoke tests run standalone on this test site.",
				)
			)

	run_name = _persist_run(results, trigger=trigger, synthetic_ran=synthetic_ran)
	_notify(run_name, results, synthetic_ran)
	frappe.db.commit()
	return run_name


def _persist_run(results, trigger, synthetic_ran):
	counts = _counts(results)
	overall = _overall(counts)
	fails = [r for r in results if r["status"] == "fail"]

	run = frappe.new_doc("Health Check Run")
	run.owner = "Administrator"  # scheduler runs as Administrator
	run.run_datetime = now_datetime()
	run.site = frappe.local.site
	run.trigger = "Manual" if trigger == "manual" else "Scheduled"
	run.overall_status = overall
	run.synthetic_ran = 1 if synthetic_ran else 0
	run.pass_count = counts["pass"]
	run.warn_count = counts["warn"]
	run.fail_count = counts["fail"]
	run.total_checks = len(results)
	run.summary = (
		f"{overall}: {counts['pass']} pass / {counts['warn']} warn / {counts['fail']} fail."
		+ (f" First failure: {fails[0]['title']}." if fails else " All systems healthy.")
	)
	for r in results:
		run.append(
			"results",
			{
				"check_key": r["key"],
				"title": r["title"],
				"stage": r["stage"],
				"status": r["status"],
				"detail": (r["detail"] or "")[:500],
				"remediation": (r["remediation"] or "")[:500],
				"evidence": (r["evidence"] or "")[:500],
			},
		)
	run.flags.ignore_permissions = True
	run.insert(ignore_permissions=True)
	return run.name


# ---------------------------------------------------------------------------
# In-ERP digest (Notification Log + realtime toast). No email / webhook.
# ---------------------------------------------------------------------------


def _digest_recipients():
	"""Configured recipients (CSV/newline) else every enabled System Manager."""
	users = []
	csv = frappe.db.get_single_value(SETTINGS, "health_digest_recipients")
	if csv:
		users = [u.strip() for u in csv.replace(",", "\n").splitlines() if u.strip()]
	if not users:
		holders = frappe.get_all(
			"Has Role",
			filters={"role": "System Manager", "parenttype": "User"},
			pluck="parent",
		)
		users = [u for u in set(holders) if frappe.db.get_value("User", u, "enabled")]
	# Never notify the system pseudo-users.
	return sorted(u for u in set(users) if u not in ("Administrator", "Guest"))


def _build_digest_html(run_name, overall, counts, results, synthetic_ran, url):
	fails = [r for r in results if r["status"] == "fail"]
	warns = [r for r in results if r["status"] == "warn"]
	dot = {"Green": "🟢", "Amber": "🟡", "Red": "🔴"}[overall]
	lines = [
		f"<p>{dot} <b>Lumirise self-test: {overall}</b> &mdash; "
		f"{counts['pass']} pass / {counts['warn']} warn / {counts['fail']} fail"
		f"{' (synthetic tier ran)' if synthetic_ran else ''}.</p>"
	]
	if not fails and not warns:
		lines.append("<p>All systems healthy. ✅</p>")

	def _block(title, rows):
		if not rows:
			return ""
		out = [f"<p><b>{title}</b></p><ul>"]
		for r in rows:
			fix = f"<br><i>Fix:</i> {frappe.utils.escape_html(r['remediation'])}" if r["remediation"] else ""
			out.append(
				f"<li><b>[{frappe.utils.escape_html(r['stage'])}]</b> "
				f"{frappe.utils.escape_html(r['title'])} &mdash; "
				f"{frappe.utils.escape_html(r['detail'])}{fix}</li>"
			)
		out.append("</ul>")
		return "".join(out)

	lines.append(_block("Failures", fails))
	lines.append(_block("Warnings", warns))
	lines.append(f'<p><a href="{url}">Open the full Health Check Run &rarr;</a></p>')
	return "".join(lines)


def _notify(run_name, results, synthetic_ran):
	"""Push ONE rolled-up in-ERP notification per recipient. Always fires (green
	heartbeat included). Fail-safe: a notification problem never breaks the run."""
	try:
		counts = _counts(results)
		overall = _overall(counts)
		# Respect the opt-out: only-on-red suppresses green/amber heartbeats.
		if overall != "Red" and frappe.db.get_single_value(SETTINGS, "notify_only_on_red"):
			return
		url = get_url_to_form("Health Check Run", run_name)
		dot = {"Green": "🟢", "Amber": "🟡", "Red": "🔴"}[overall]
		subject = (
			f"{dot} Health Check {overall}: "
			f"{counts['pass']}✓ {counts['warn']}! {counts['fail']}✗"
		)
		body = _build_digest_html(run_name, overall, counts, results, synthetic_ran, url)
		for user in _digest_recipients():
			try:
				frappe.get_doc(
					{
						"doctype": "Notification Log",
						"for_user": user,
						"from_user": "Administrator",
						"type": "Alert",
						"document_type": "Health Check Run",
						"document_name": run_name,
						"subject": subject,
						"email_content": body,
					}
				).insert(ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"Health Check: notify {user} failed")
		frappe.publish_realtime(
			"msgprint",
			{
				"message": subject,
				"title": "Lumirise Health Check",
				"indicator": {"Green": "green", "Amber": "orange", "Red": "red"}[overall],
			},
			after_commit=True,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Health Check: notify failed")


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------


@frappe.whitelist()
def trigger_health_check():
	"""Admin-only on-demand run. Enqueues so the request returns immediately;
	deduped so overlapping manual runs cannot race the synthetic data."""
	frappe.only_for("System Manager")
	from frappe.utils.background_jobs import is_job_enqueued

	job_id = "lumirise_health_check_manual"
	if is_job_enqueued(job_id):
		return {"queued": False, "reason": "A health check is already running."}
	frappe.enqueue(
		"lumirise_custom.health_check.run_daily_health_check",
		queue="long",
		timeout=1500,
		job_id=job_id,
		trigger="manual",
	)
	return {"queued": True}


# ---------------------------------------------------------------------------
# Synthetic tier + triple fail-closed gate
# ---------------------------------------------------------------------------


def _synthetic_allowed():
	"""The destructive tier runs ONLY when explicitly enabled AND the site is not
	production. Fails CLOSED — any doubt and it does not run."""
	try:
		if not frappe.db.get_single_value(SETTINGS, "enable_destructive_health_tests"):
			return False
		prod_site = (frappe.db.get_single_value(SETTINGS, "production_site_name") or "").strip()
		if prod_site and frappe.local.site == prod_site:
			return False
		# site_config kill switch — survives a DB restore onto prod.
		if frappe.conf.get("is_production_site"):
			return False
		return True
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Health Check: _synthetic_allowed gate failed")
		return False


def _run_synthetic_tier():
	return [_run_sales_smoke(), _run_full_smoke()]


def _run_sales_smoke():
	"""sales_smoke_test: idempotent, self-cleaning, exposes a per-check results
	list, and RAISES frappe.ValidationError at the end if any check failed."""
	from lumirise_custom.demo import sales_smoke_test as sst

	try:
		sst.results.clear()
	except Exception:
		pass
	raised = None
	try:
		sst.run()
	except Exception as e:
		raised = str(e)
		frappe.log_error(frappe.get_traceback(), "Health Check: sales_smoke_test failed")
	rows = list(getattr(sst, "results", []) or [])
	failed = [r for r in rows if not r[1]]
	status = "fail" if (failed or raised) else "pass"
	return _result(
		"synthetic_sales_chain",
		"Synthetic: RM landed cost → BOM costing → Price Sheet → Quotation",
		SYNTHETIC,
		status,
		detail=(
			f"{len(rows) - len(failed)}/{len(rows)} pricing/costing assertions passed."
			if rows
			else "Sales smoke test produced no assertions (it errored early)."
		),
		remediation=(
			"The pricing/costing engine (costing.py / pricing_engine.py) is not "
			"producing expected values — open the failing assertion's doctype; see Error Log."
		)
		if status == "fail"
		else "",
		evidence="; ".join(r[0] for r in failed[:5]),
	)


def _run_full_smoke():
	"""smoke_test: drives the full order-to-dispatch chain. It COMMITS real docs
	and does NOT raise, so we always cleanup() in a finally."""
	from lumirise_custom.demo import smoke_test as smk

	# Precondition: demo masters must exist on the test site. Absent => skip (warn),
	# not a scary red.
	if not frappe.db.exists("Item", "LED-PANEL-24W"):
		return _result(
			"synthetic_e2e_chain",
			"Synthetic: SO → Plan → PO → Vendor PDI → IQC gate → GRN → Manufacture → PDI gate → Dispatch",
			SYNTHETIC,
			"warn",
			detail="Demo masters (e.g. Item LED-PANEL-24W) are not present on this test site.",
			remediation="Seed the demo masters on the test site before enabling the synthetic E2E tier.",
		)

	err = None
	try:
		smk.run()
	except Exception:
		err = frappe.get_traceback()
		frappe.log_error(err, "Health Check: full smoke_test.run failed")
	finally:
		try:
			smk.cleanup()
			frappe.db.commit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Health Check: full smoke_test.cleanup failed")
	status = "fail" if err else "pass"
	return _result(
		"synthetic_e2e_chain",
		"Synthetic: SO → Plan → PO → Vendor PDI → IQC gate → GRN → Manufacture → PDI gate → Dispatch",
		SYNTHETIC,
		status,
		detail="Full order-to-dispatch E2E completed; IQC + Customer PDI gates exercised."
		if not err
		else "The order-to-dispatch chain aborted before completing.",
		remediation="A step in the order-to-dispatch chain broke — see Error Log (title 'full smoke_test.run failed') for the traceback and the last printed step."
		if err
		else "",
	)


# ===========================================================================
# READ-ONLY CHECKS  (non-destructive; safe on the live site)
# ===========================================================================


def _parent_boms():
	return frappe.get_all(
		"BOM",
		filters={"docstatus": 1, "is_active": 1, "custom_bom_type": "Parent BOM"},
		fields=[
			"name",
			"custom_bom_cost",
			"custom_raw_materials_total",
			"custom_1k_moq_price",
			"custom_3k_moq_price",
			"custom_6k_moq_price",
			"custom_10k_moq_price",
		],
	)


@readonly_check("bom_cost_rollup", "Submitted Parent BOMs have a non-zero cost", COSTING)
def _check_bom_cost_rollup():
	boms = _parent_boms()
	bad = [b for b in boms if flt(b.custom_bom_cost) <= 0]
	if not boms:
		return _result("", "", "", "pass", detail="No active Parent BOMs to check.")
	if bad:
		return _result(
			"",
			"",
			"",
			"fail",
			detail=f"{len(bad)} of {len(boms)} active Parent BOMs have a zero/blank rolled-up cost.",
			remediation="Open each BOM and Save to re-run the costing rollup, or fix the raw-material valuation_rate feeding it (costing.py compute).",
			evidence=", ".join(b.name for b in bad[:5]),
		)
	return _result("", "", "", "pass", detail=f"All {len(boms)} Parent BOMs costed.")


@readonly_check("bom_rm_rollup", "Parent BOM raw-material subtotal rolls up", COSTING)
def _check_bom_rm_rollup():
	boms = _parent_boms()
	bad = [b for b in boms if flt(b.custom_bom_cost) > 0 and flt(b.custom_raw_materials_total) <= 0]
	if bad:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(bad)} costed Parent BOMs have a zero raw-material subtotal.",
			remediation="RM cost is not rolling into custom_raw_materials_total — check child item valuation_rate / Sub-BOM totals (costing.py).",
			evidence=", ".join(b.name for b in bad[:5]),
		)
	return _result("", "", "", "pass", detail="RM subtotals roll up.")


@readonly_check("moq_slabs_populated", "MOQ slab prices are populated", COSTING)
def _check_moq_slabs():
	boms = _parent_boms()
	slab_fields = ["custom_1k_moq_price", "custom_3k_moq_price", "custom_6k_moq_price", "custom_10k_moq_price"]
	bad = [b for b in boms if flt(b.custom_bom_cost) > 0 and any(flt(b.get(f)) <= 0 for f in slab_fields)]
	if bad:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(bad)} costed Parent BOMs are missing one or more MOQ slab prices (1k/3k/6k/10k).",
			remediation="Set the custom_{1k,3k,6k,10k}_moq_percentage on the BOM and Save so the slab prices recompute.",
			evidence=", ".join(b.name for b in bad[:5]),
		)
	return _result("", "", "", "pass", detail="MOQ slabs populated on all costed BOMs.")


@readonly_check("so_shipped_not_completed", "Shipped Sales Orders are marked Completed", STATUS)
def _check_so_shipped_not_completed():
	rows = frappe.get_all(
		"Delivery Note Item",
		filters={"docstatus": 1, "against_sales_order": ["is", "set"]},
		fields=["against_sales_order"],
		distinct=True,
	)
	so_names = sorted({r.against_sales_order for r in rows if r.against_sales_order})
	if not so_names:
		return _result("", "", "", "pass", detail="No shipped Sales Orders to check.")
	stuck = frappe.get_all(
		"Sales Order",
		filters={"name": ["in", so_names], "lr_production_status": ["in", ["", "Pending", "In Production"]]},
		fields=["name", "lr_production_status"],
	)
	if stuck:
		return _result(
			"",
			"",
			"",
			"fail",
			detail=f"{len(stuck)} Sales Orders have a submitted Delivery Note but production status is not Completed.",
			remediation="status_sync did not advance the SO — resubmit the Work Order / Delivery Note, or check Error Log for a status_sync failure.",
			evidence=", ".join(s.name for s in stuck[:5]),
		)
	return _result("", "", "", "pass", detail=f"All {len(so_names)} shipped SOs marked Completed.")


@readonly_check("so_status_consistent", "Sales Order status fields are consistent", STATUS)
def _check_so_status_consistent():
	sos = frappe.get_all(
		"Sales Order",
		filters={"docstatus": 1},
		fields=["name", "lr_planning_status", "lr_purchase_status", "lr_production_status"],
		limit_page_length=0,
	)
	planned = ("Planned",)
	purchase_advanced = ("Ordered", "Received")
	prod_advanced = ("In Production", "Completed")
	bad = []
	for s in sos:
		planning_pending = (s.lr_planning_status or "Pending") == "Pending"
		if planning_pending and (
			(s.lr_production_status in prod_advanced) or (s.lr_purchase_status in purchase_advanced)
		):
			bad.append(s.name)
	if bad:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(bad)} Sales Orders are inconsistent (purchase/production advanced while planning is still Pending).",
			remediation="The planning status never advanced — re-run status_sync.on_material_planning_submit (resubmit the Material Plan) or backfill lr_planning_status.",
			evidence=", ".join(bad[:5]),
		)
	return _result("", "", "", "pass", detail=f"{len(sos)} submitted SOs status-consistent.")


def _hooked(doctype, event, handler):
	"""True if `handler` is wired on doctype/event in the merged doc_events hooks."""
	events = frappe.get_hooks("doc_events") or {}
	dt = events.get(doctype) or {}
	wired = dt.get(event) or []
	if isinstance(wired, str):
		wired = [wired]
	return handler in wired


@readonly_check("iqc_gate_wired", "IQC gate is wired on Purchase Receipt", GATES)
def _check_iqc_gate():
	if _hooked("Purchase Receipt", "before_submit", "lumirise_custom.events.iqc_gate"):
		return _result("", "", "", "pass", detail="iqc_gate active on Purchase Receipt before_submit.")
	return _result(
		"",
		"",
		"",
		"fail",
		detail="The IQC gate is NOT wired on Purchase Receipt before_submit.",
		remediation="GRNs can post without IQC. Restore 'lumirise_custom.events.iqc_gate' in hooks.py doc_events and run bench migrate.",
	)


@readonly_check("pdi_gate_wired", "Customer PDI gate is wired on Delivery Note", GATES)
def _check_pdi_gate():
	if _hooked("Delivery Note", "before_submit", "lumirise_custom.events.customer_pdi_gate"):
		return _result("", "", "", "pass", detail="customer_pdi_gate active on Delivery Note before_submit.")
	return _result(
		"",
		"",
		"",
		"fail",
		detail="The Customer PDI gate is NOT wired on Delivery Note before_submit.",
		remediation="Dispatch can happen without PDI. Restore 'lumirise_custom.events.customer_pdi_gate' in hooks.py doc_events and run bench migrate.",
	)


@readonly_check("backflush_mode", "Backflush mode is transfer-based", PRODUCTION)
def _check_backflush_mode():
	val = frappe.db.get_single_value("Manufacturing Settings", "backflush_raw_materials_based_on")
	want = "Material Transferred for Manufacture"
	if val == want:
		return _result("", "", "", "pass", detail=f"backflush_raw_materials_based_on = '{want}'.")
	return _result(
		"",
		"",
		"",
		"fail",
		detail=f"Backflush mode is '{val}', expected '{want}'.",
		remediation=f"Set Manufacturing Settings → Backflush Raw Materials Based On = '{want}' so line consumption matches what was transferred.",
	)


_TASK_HANDLERS = {
	"Sales Order": ("on_update", "lumirise_custom.task_engine.on_sales_order_update"),
	"Material Planning": ("on_submit", "lumirise_custom.task_engine.on_material_planning_submit"),
	"Indent": ("on_update", "lumirise_custom.task_engine.on_indent_update"),
	"IQC": ("on_submit", "lumirise_custom.task_engine.on_iqc_submit"),
	"Customer PDI": ("on_submit", "lumirise_custom.task_engine.on_customer_pdi_submit"),
	"Delivery Note": ("on_submit", "lumirise_custom.task_engine.on_delivery_note_submit"),
	"Work Order": ("on_submit", "lumirise_custom.task_engine.on_work_order_submit"),
	"Purchase Receipt": ("on_submit", "lumirise_custom.task_engine.on_purchase_receipt_submit"),
	"Material Request": ("on_submit", "lumirise_custom.task_engine.on_material_request_submit"),
	"Stock Entry": ("on_submit", "lumirise_custom.task_engine.on_stock_entry_submit"),
}


@readonly_check("task_handlers_wired", "Task-engine handoff handlers are wired", TASKS)
def _check_task_handlers():
	missing = [
		f"{dt}.{event}"
		for dt, (event, handler) in _TASK_HANDLERS.items()
		if not _hooked(dt, event, handler)
	]
	if missing:
		return _result(
			"",
			"",
			"",
			"fail",
			detail=f"{len(missing)} of {len(_TASK_HANDLERS)} task-engine handoff handlers are unwired.",
			remediation="Cross-department Kanban handoffs will stop generating. Restore the missing doc_events in hooks.py and run bench migrate.",
			evidence=", ".join(missing[:6]),
		)
	return _result("", "", "", "pass", detail=f"All {len(_TASK_HANDLERS)} task-engine handlers wired.")


@readonly_check("recent_so_planning_task", "Recently approved SOs raised a Planning task", TASKS)
def _check_recent_so_planning_task():
	cutoff = add_to_date(now_datetime(), days=-7)
	recent = frappe.get_all(
		"Sales Order",
		filters={"docstatus": 1, "creation": [">=", cutoff]},
		fields=["name"],
		limit_page_length=0,
	)
	if not recent:
		return _result("", "", "", "pass", detail="No Sales Orders submitted in the last 7 days.")
	tasked = set(
		frappe.get_all(
			"Lumirise Task",
			filters={
				"source_event": "so_approved",
				"reference_doctype": "Sales Order",
				"reference_name": ["in", [r.name for r in recent]],
			},
			fields=["reference_name"],
			pluck="reference_name",
		)
	)
	missing = [r.name for r in recent if r.name not in tasked]
	if missing:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(missing)} of {len(recent)} recent Sales Orders have no Planning handoff task.",
			remediation="The task engine may have errored at SO approval — check Error Log; the SO may not have reached the approved workflow state yet.",
			evidence=", ".join(missing[:5]),
		)
	return _result("", "", "", "pass", detail=f"All {len(recent)} recent SOs raised a Planning task.")


@readonly_check("line_user_perm", "Production-line scoping is configured", PERMISSIONS)
def _check_line_user_perm():
	lines = frappe.get_all("User Permission", filters={"allow": "Lumirise Production Line"}, limit=1)
	settings = frappe.get_cached_doc(SETTINGS)
	active_lines = [r for r in (settings.production_lines or []) if r.is_active]
	if active_lines and not lines:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(active_lines)} production lines are configured but no per-line User Permission scoping exists.",
			remediation="Line operators may see every line's data. Add User Permissions scoping line users to their Lumirise Production Line.",
		)
	return _result("", "", "", "pass", detail="Line scoping present or no lines configured yet.")


@readonly_check("line_warehouses", "Each production line has a valid warehouse", WAREHOUSES)
def _check_line_warehouses():
	settings = frappe.get_cached_doc(SETTINGS)
	active = [r for r in (settings.production_lines or []) if r.is_active]
	if not active:
		return _result(
			"",
			"",
			"",
			"warn",
			detail="No active production lines are configured.",
			remediation="Configure the production lines (with a warehouse each) in Lumirise Operations Settings → Production Lines.",
		)
	bad = [
		r.line_name or "(unnamed)"
		for r in active
		if not r.line_warehouse or not frappe.db.exists("Warehouse", r.line_warehouse)
	]
	if bad:
		return _result(
			"",
			"",
			"",
			"fail",
			detail=f"{len(bad)} active production lines have no/invalid warehouse.",
			remediation="Set a valid Warehouse for each active line in Lumirise Operations Settings → Production Lines.",
			evidence=", ".join(bad[:6]),
		)
	return _result("", "", "", "pass", detail=f"All {len(active)} active lines have a valid warehouse.")


@readonly_check("core_warehouses", "Core operational warehouses are configured", WAREHOUSES)
def _check_core_warehouses():
	fields = {
		"rm_warehouse": "Raw Material Store",
		"shop_floor_warehouse": "Shop Floor",
		"fg_warehouse": "Production FG Store",
		"dispatch_fg_warehouse": "Dispatch FG Store",
		"pdi_warehouse": "Customer PDI Store",
	}
	settings = frappe.get_cached_doc(SETTINGS)
	bad = []
	for field, label in fields.items():
		val = settings.get(field)
		if not val or not frappe.db.exists("Warehouse", val):
			bad.append(label)
	if bad:
		return _result(
			"",
			"",
			"",
			"fail",
			detail=f"{len(bad)} core warehouses are unset or point at a missing Warehouse.",
			remediation="Configure them in Lumirise Operations Settings — the flow will throw at runtime otherwise.",
			evidence=", ".join(bad),
		)
	return _result("", "", "", "pass", detail="All core warehouses configured.")


@readonly_check("scheduler_alive", "The bench scheduler is running", SCHEDULER)
def _check_scheduler_alive():
	try:
		from frappe.utils.scheduler import is_scheduler_inactive

		if is_scheduler_inactive():
			return _result(
				"",
				"",
				"",
				"warn",
				detail="The scheduler is inactive on this site — daily automations are not firing.",
				remediation="Run `bench --site <site> enable-scheduler` and check `bench doctor`.",
			)
	except Exception:
		pass
	last = frappe.get_all("Scheduled Job Log", fields=["creation"], order_by="creation desc", limit=1)
	if last:
		age = now_datetime() - frappe.utils.get_datetime(last[0].creation)
		if age.total_seconds() > 25 * 3600:
			return _result(
				"",
				"",
				"",
				"warn",
				detail=f"No scheduled job has logged in {round(age.total_seconds() / 3600)}h.",
				remediation="The scheduler may be stalled — check `bench doctor` and the worker logs.",
			)
	return _result("", "", "", "pass", detail="Scheduler active.")


@readonly_check("error_log_spike", "Error Log is not spiking", SCHEDULER)
def _check_error_log_spike():
	threshold = cint(frappe.db.get_single_value(SETTINGS, "health_error_log_threshold")) or 50
	cutoff = add_to_date(now_datetime(), hours=-24)
	count = frappe.db.count("Error Log", {"creation": [">=", cutoff]})
	if count >= threshold:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{count} Error Log entries in the last 24h (threshold {threshold}).",
			remediation="Open Error Log, group by title — a handler is likely throwing repeatedly.",
			evidence=f"{count} errors / 24h",
		)
	return _result("", "", "", "pass", detail=f"{count} Error Log entries / 24h (under {threshold}).")


@readonly_check("artifact_drift", "Customisation counts match the baseline", DRIFT)
def _check_artifact_drift():
	checks = [
		("baseline_server_scripts", frappe.db.count("Server Script"), "Server Scripts"),
		("baseline_client_scripts", frappe.db.count("Client Script"), "Client Scripts"),
		(
			"baseline_custom_fields",
			frappe.db.count("Custom Field", {"module": "Lumirise Custom"}),
			"Custom Fields (Lumirise Custom)",
		),
	]
	drift = []
	for field, current, label in checks:
		baseline = cint(frappe.db.get_single_value(SETTINGS, field))
		if baseline and current != baseline:
			drift.append(f"{label}: {current} vs baseline {baseline}")
	if drift:
		return _result(
			"",
			"",
			"",
			"warn",
			detail="Customisation drift detected vs the recorded baseline.",
			remediation="Reconcile an unexpected migration/uninstall, or update the baseline counts in Lumirise Operations Settings if the change was intentional.",
			evidence="; ".join(drift),
		)
	return _result("", "", "", "pass", detail="No drift (or no baseline set).")


@readonly_check("negative_stock_off", "Allow Negative Stock is off", STOCK)
def _check_negative_stock():
	if cint(frappe.db.get_single_value("Stock Settings", "allow_negative_stock")):
		return _result(
			"",
			"",
			"",
			"fail",
			detail="Stock Settings → Allow Negative Stock is ON.",
			remediation="Turn it off unless mid-migration — it bypasses over-issue/over-receipt guards (incl. subcontracting theft detection).",
		)
	return _result("", "", "", "pass", detail="Allow Negative Stock is off.")


@readonly_check("over_receipt_guard", "Over-receipt allowance is sane", STOCK)
def _check_over_receipt_guard():
	allowance = flt(frappe.db.get_single_value("Stock Settings", "over_delivery_receipt_allowance"))
	cap = flt(frappe.db.get_single_value(SETTINGS, "health_over_receipt_cap")) or 10.0
	if allowance > cap:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"Over-delivery/receipt allowance is {allowance}% (cap {cap}%).",
			remediation="GRN/DN can exceed ordered qty — lower Stock Settings → Over Delivery/Receipt Allowance.",
		)
	return _result("", "", "", "pass", detail=f"Over-receipt allowance {allowance}% (≤ {cap}%).")


@readonly_check(
	"auto_reserve_on_purchase_off", "Auto-reserve FG for SO on purchase is off", STOCK
)
def _check_auto_reserve_on_purchase():
	if cint(
		frappe.db.get_single_value(
			"Stock Settings", "auto_reserve_stock_for_sales_order_on_purchase"
		)
	):
		return _result(
			"",
			"",
			"",
			"fail",
			detail="Stock Settings → Auto Reserve Stock for Sales Order on Purchase is ON.",
			remediation=(
				"Turn it OFF. Lumirise reserves FG late/opt-in at Dispatch FG; auto-reserving "
				"pins a Stock Reservation Entry at a transit warehouse and blocks move_to_dispatch "
				"(the 2026-06-17 incident)."
			),
		)
	return _result(
		"", "", "", "pass",
		detail="Auto-reserve FG for SO on purchase is off (late/opt-in reservation).",
	)


@readonly_check(
	"dept_map_users_filled", "Active Department Map rows have supervisor/HOD users", TASKS
)
def _check_dept_map_users():
	rows = frappe.get_all(
		"Lumirise Department Map",
		filters={"is_active": 1},
		fields=["name", "supervisor_user", "hod_user"],
		limit_page_length=0,
	)
	if not rows:
		return _result(
			"",
			"",
			"",
			"warn",
			detail="No active Lumirise Department Map rows.",
			remediation="Seed departments: bench --site site.com execute lumirise_custom.setup.task_seed.seed_departments",
		)
	unfilled = [r.name for r in rows if not (r.supervisor_user or r.hod_user)]
	if unfilled:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(unfilled)} of {len(rows)} active departments have no supervisor/HOD user — their handoff tasks are created unassigned.",
			remediation="Fill supervisor_user + hod_user on each Lumirise Department Map row so Kanban handoffs get an owner.",
			evidence=", ".join(unfilled[:8]),
		)
	return _result(
		"", "", "", "pass",
		detail=f"All {len(rows)} active departments have at least one user mapped.",
	)


@readonly_check(
	"jobcard_miss_has_task", "Missed Job Cards raised an escalation task", TASKS
)
def _check_jobcard_miss_task():
	missed = frappe.get_all(
		"Lumirise Job Card",
		filters={"docstatus": 1, "status": "Missed"},
		pluck="name",
	)
	if not missed:
		return _result("", "", "", "pass", detail="No missed Job Cards.")
	tasked = set(
		frappe.get_all(
			"Lumirise Task",
			filters={
				"source_event": "job_card_missed_target",
				"reference_doctype": "Lumirise Job Card",
				"reference_name": ["in", missed],
			},
			pluck="reference_name",
		)
	)
	missing = [m for m in missed if m not in tasked]
	if missing:
		return _result(
			"",
			"",
			"",
			"fail",
			detail=f"{len(missing)} of {len(missed)} missed Job Cards have no escalation task.",
			remediation="Job Card _raise_miss_alert did not fire — check task_engine.create_task and the Error Log.",
			evidence=", ".join(missing[:8]),
		)
	return _result(
		"", "", "", "pass",
		detail=f"All {len(missed)} missed Job Cards raised an escalation task.",
	)


@readonly_check("wo_dates_set", "Open Work Orders have schedule dates", PRODUCTION)
def _check_wo_dates():
	rows = frappe.get_all(
		"Work Order",
		filters={"docstatus": 1, "status": ["not in", ["Completed", "Stopped", "Closed"]]},
		or_filters={
			"planned_start_date": ["is", "not set"],
			"expected_delivery_date": ["is", "not set"],
		},
		pluck="name",
		limit_page_length=0,
	)
	if rows:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(rows)} open Work Order(s) have no planned-start / expected-delivery date.",
			remediation="Material Planning stamps these from item lead time on Post (WP-1.2). Work Orders created before that fix, or by hand, lack them — set the dates or let them complete.",
			evidence=", ".join(rows[:8]),
		)
	return _result("", "", "", "pass", detail="All open Work Orders carry schedule dates.")


@readonly_check("so_po_exceptions", "Submitted Sales Orders have no open PO-match exception", STATUS)
def _check_so_po_exceptions():
	rows = frappe.get_all(
		"Sales Order",
		filters={"docstatus": 1, "lr_po_match_status": "Exception"},
		pluck="name",
		limit_page_length=0,
	)
	if rows:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(rows)} submitted Sales Order(s) flagged as a PO-match exception (blank/duplicate customer PO, or a line drifting from its Quotation).",
			remediation="Open each SO's 'PO Match Note' and reconcile with the customer PO. Advisory in v1 — structured line-level PO capture is v2.",
			evidence=", ".join(rows[:8]),
		)
	return _result("", "", "", "pass", detail="No submitted Sales Orders in PO-match exception.")


@readonly_check("lines_have_supervisor", "Active production lines have a supervisor user", PRODUCTION)
def _check_lines_have_supervisor():
	settings = frappe.get_cached_doc("Lumirise Operations Settings")
	rows = [r for r in settings.production_lines if r.is_active]
	if not rows:
		return _result(
			"",
			"",
			"",
			"warn",
			detail="No active production lines configured.",
			remediation="Add production lines (each = a Warehouse) on Lumirise Operations Settings.",
		)
	missing = [r.line_name for r in rows if not r.supervisor_user]
	if missing:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(missing)} of {len(rows)} active production lines have no supervisor user.",
			remediation="Set supervisor_user on each line row in Lumirise Operations Settings so daily Job Cards auto-assign to the line supervisor.",
			evidence=", ".join(missing[:8]),
		)
	return _result("", "", "", "pass", detail=f"All {len(rows)} active production lines have a supervisor.")


@readonly_check("schedule_within_so_qty", "Production Schedule slices stay within SO quantity", PRODUCTION)
def _check_schedule_within_so_qty():
	# For each submitted schedule, the sum of slice_qty per (SO, FG) must not exceed the
	# SO line quantity — otherwise the plan schedules more than was ordered.
	over = []
	lines = frappe.get_all(
		"Production Schedule Line",
		filters={"docstatus": 1, "sales_order": ["is", "set"]},
		fields=["sales_order", "fg_item", "slice_qty"],
		limit_page_length=0,
	)
	scheduled = {}
	for ln in lines:
		scheduled[(ln.sales_order, ln.fg_item)] = scheduled.get((ln.sales_order, ln.fg_item), 0) + flt(ln.slice_qty)
	for (so, fg), qty in scheduled.items():
		so_qty = flt(
			frappe.db.get_value("Sales Order Item", {"parent": so, "item_code": fg}, "qty")
		)
		if so_qty and qty > so_qty + 0.001:
			over.append(f"{so}/{fg}: scheduled {qty:g} > ordered {so_qty:g}")
	if over:
		return _result(
			"",
			"",
			"",
			"fail",
			detail=f"{len(over)} SO/FG slice(s) scheduled beyond the ordered quantity.",
			remediation="Reduce the over-scheduled slices — the plan must not exceed the Sales Order quantity.",
			evidence="; ".join(over[:6]),
		)
	return _result("", "", "", "pass", detail="All scheduled slices are within their Sales Order quantity.")


@readonly_check("jobcard_schedule_ref_valid", "Scheduled Job Cards reference a live schedule", PRODUCTION)
def _check_jobcard_schedule_ref():
	jcs = frappe.get_all(
		"Lumirise Job Card",
		filters={"schedule_ref": ["is", "set"], "docstatus": ["<", 2]},
		fields=["name", "schedule_ref"],
		limit_page_length=0,
	)
	orphan = [
		j.name
		for j in jcs
		if not frappe.db.exists("Lumirise Production Schedule", {"name": j.schedule_ref, "docstatus": 1})
	]
	if orphan:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(orphan)} released Job Card(s) point to a missing/cancelled Production Schedule.",
			remediation="A schedule was cancelled after its day was released. Reconcile the orphaned Job Cards (cancel or re-attach).",
			evidence=", ".join(orphan[:8]),
		)
	return _result("", "", "", "pass", detail="All scheduled Job Cards reference a live schedule.")


@readonly_check("rm_price_ranges_valid", "RM Price Book qty ranges are sane", COSTING)
def _check_rm_price_ranges():
	bad = frappe.db.sql(
		"""SELECT i.parent, i.item_code FROM `tabRM Price Book Item` i
		   JOIN `tabRM Price Book` p ON p.name = i.parent
		   WHERE p.docstatus = 1 AND i.min_qty > 0 AND i.max_qty > 0 AND i.min_qty > i.max_qty""",
		as_dict=True,
	)
	if bad:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(bad)} RM Price Book row(s) have Min Qty > Max Qty (the qty-range rate can never match).",
			remediation="Fix the min/max on those RM Price Book rows so the qty-range price resolves.",
			evidence=", ".join(f"{b.parent}:{b.item_code}" for b in bad[:6]),
		)
	return _result("", "", "", "pass", detail="RM Price Book qty ranges are consistent.")


@readonly_check("rm_rejection_overdue", "Overdue RM rejections have a scrap-review task", STOCK)
def _check_rm_rejection_overdue():
	from lumirise_custom.stores import aged_rejection_rows

	overdue = [r["item_code"] for r in aged_rejection_rows() if r["status"] == "Scrap due"]
	if not overdue:
		return _result("", "", "", "pass", detail="No RM rejections past the hold window.")
	tasked = set(
		frappe.get_all(
			"Lumirise Task",
			filters={"source_event": "rm_rejection_hold", "reference_name": ["in", overdue]},
			pluck="reference_name",
		)
	)
	missing = [i for i in overdue if i not in tasked]
	if missing:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(missing)} item(s) past the rejection hold window with no scrap-review task — the hold-timer may not have run.",
			remediation="Check the daily scheduler; run lumirise_custom.stores.flag_overdue_rm_rejections. Disposition stays manual (Praveen + Quality).",
			evidence=", ".join(missing[:8]),
		)
	return _result("", "", "", "pass", detail=f"All {len(overdue)} overdue RM rejection(s) have a scrap-review task.")


@readonly_check("container_release_gate_wired", "Container-release gate is wired on GRN", GATES)
def _check_container_release_wired():
	if not _hooked("Purchase Receipt", "before_submit", "lumirise_custom.events.container_release_gate"):
		return _result(
			"",
			"",
			"",
			"fail",
			detail="events.container_release_gate is not wired on Purchase Receipt before_submit.",
			remediation="Restore the container_release_gate handler in hooks.py and run bench migrate.",
		)
	stuck = frappe.get_all(
		"Inbound Logistics",
		filters={"docstatus": 1, "status": "Reached Warehouse", "release_status": "Pending Authorization"},
		pluck="name",
		limit_page_length=0,
	)
	if stuck:
		return _result(
			"",
			"",
			"",
			"warn",
			detail=f"{len(stuck)} consignment(s) Reached Warehouse but not released by Purchase.",
			remediation="Purchase should Release Container on those Inbound Logistics, or explain the hold.",
			evidence=", ".join(stuck[:8]),
		)
	return _result("", "", "", "pass", detail="Container-release gate wired; no consignments stuck unreleased.")
