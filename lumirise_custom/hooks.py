app_name = "lumirise_custom"
app_title = "Lumirise Custom"
app_publisher = "riddhi solanki"
app_description = "Lumirise CUstomization"
app_email = "riddhisolanki067@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "lumirise_custom",
# 		"logo": "/assets/lumirise_custom/logo.png",
# 		"title": "Lumirise Custom",
# 		"route": "/lumirise_custom",
# 		"has_permission": "lumirise_custom.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/lumirise_custom/css/lumirise_custom.css"
# app_include_js = "/assets/lumirise_custom/js/lumirise_custom.js"
app_include_js = "lumirise_overrides.bundle.js"

# include js, css files in header of web template
# web_include_css = "/assets/lumirise_custom/css/lumirise_custom.css"
# web_include_js = "/assets/lumirise_custom/js/lumirise_custom.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "lumirise_custom/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
	"Purchase Order": "public/js/purchase_order.js",
	"Sales Order": "public/js/sales_order.js",
	"Work Order": "public/js/work_order.js",
	"Stock Entry": "public/js/stock_entry.js",
	"Material Receipt": "public/js/material_receipt.js",
	"Delivery Note": "public/js/delivery_note.js",
	"Material Request": "public/js/material_request.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "lumirise_custom/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "lumirise_custom.utils.jinja_methods",
# 	"filters": "lumirise_custom.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "lumirise_custom.install.before_install"
# after_install = "lumirise_custom.install.after_install"

# Ensure roles referenced by DocType JSON exist BEFORE schema sync.
before_migrate = "lumirise_custom.setup.before_migrate"

# Sales Platform setup: roles, Item/BOM costing custom fields, credit-term seeds.
after_migrate = "lumirise_custom.setup.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "lumirise_custom.uninstall.before_uninstall"
# after_uninstall = "lumirise_custom.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "lumirise_custom.utils.before_app_install"
# after_app_install = "lumirise_custom.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "lumirise_custom.utils.before_app_uninstall"
# after_app_uninstall = "lumirise_custom.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "lumirise_custom.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "lumirise_custom.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Ship the Lumirise customisations as fixtures.
# NOTE (Ajay review 2026-06-14): Workflows + their states/actions are NO LONGER
# shipped as fixtures. They are managed idempotently in code via
# lumirise_custom.setup.approval_setup.setup_approvals (run on after_migrate) so the
# Indent->Planning Manager and Purchase Order->Purchase Head approval chains are the
# single source of truth and cannot be overwritten by a stale fixture import.
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Lumirise Custom"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "Lumirise Custom"]]},
	{"dt": "Workspace", "filters": [["module", "=", "Lumirise Custom"]]},
]

# Focus 9 quality gates on standard ERPNext documents.
# NOTE: several events carry TWO handlers (list form) — the existing business
# handler PLUS the Lumirise task-engine handler that auto-creates the handoff /
# defect Kanban card. The task-engine handlers are fail-safe and never block.
doc_events = {
	"Purchase Receipt": {
		"before_submit": [
			"lumirise_custom.events.iqc_gate",
			# Warn/block if the PO's Inbound Logistics wasn't released by Purchase (WP-2.3).
			"lumirise_custom.events.container_release_gate",
		],
		"on_submit": [
			# GRN posted -> RM Stores put-away card.
			"lumirise_custom.task_engine.on_purchase_receipt_submit",
			# GRN posted -> SO purchase status = Received.
			"lumirise_custom.status_sync.on_purchase_receipt_submit",
			# GRN posted -> refresh item cost + dependent BOM costs.
			"lumirise_custom.costing.on_purchase_receipt",
			# GRN posted -> close the IQC (status Moved to RM) so its accepted qty
			# leaves the "Pending IQC" bucket in Material Planning (now real stock).
			"lumirise_custom.chain.mark_iqc_moved_to_rm",
			# GRN posted -> realise any pre-GRN IQC samples into the IQC Lab store
			# (RM Store -> IQC Lab), now that the goods are owned. Fail-safe (10.1).
			"lumirise_custom.samples.realise_samples_to_lab",
		],
		# GRN cancelled -> re-open the IQC so the qty returns to "Pending IQC", and
		# reverse any un-dispositioned IQC Lab sample transfers.
		"on_cancel": [
			"lumirise_custom.chain.revert_iqc_moved_to_rm",
			"lumirise_custom.samples.revert_samples_from_lab",
		],
		# Stamp the SO/Indent/WO/PO traceability panel (fail-safe).
		"validate": "lumirise_custom.traceability.stamp",
	},
	"Delivery Note": {
		"before_submit": "lumirise_custom.events.customer_pdi_gate",
		# Dispatched -> task Accounts to raise the Sales Invoice.
		"on_submit": "lumirise_custom.task_engine.on_delivery_note_submit",
		"validate": "lumirise_custom.traceability.stamp",
	},
	"Sales Invoice": {
		# Stamp the SO/Indent/WO/PO traceability panel (fail-safe).
		"validate": "lumirise_custom.traceability.stamp",
		# On invoice -> move FG Production FG -> Dispatch FG (behind auto_move_fg_on_si,
		# default OFF; only the one unambiguous hop — WP-3.3). Fail-safe.
		"on_submit": "lumirise_custom.accounts.auto_move_fg_to_dispatch",
	},
	"Purchase Invoice": {
		"validate": [
			# Stamp the SO/Indent/WO/PO traceability panel from the PI's Purchase Order(s).
			"lumirise_custom.traceability.stamp",
			# Stamp the GRN Date from the linked Purchase Receipt(s) (latest receipt).
			"lumirise_custom.accounts.set_grn_date",
		],
		# Bill entered for full received qty -> auto-draft a Debit Note for the
		# rejected qty (traced from the GRN), pending user approval. Fail-safe.
		"on_submit": "lumirise_custom.accounts.auto_debit_note_for_rejections",
	},
	"Purchase Order": {
		"validate": "lumirise_custom.traceability.stamp",
		"on_submit": [
			# Flag the source Indents Ordered once the PO they fed is submitted.
			"lumirise_custom.lumirise_custom.doctype.indent.indent.mark_indents_ordered",
			# SO purchase status = Ordered.
			"lumirise_custom.status_sync.on_purchase_order_submit",
		],
		"on_cancel": "lumirise_custom.lumirise_custom.doctype.indent.indent.unmark_indents_ordered",
	},
	# Lumirise costing chain (Item landed cost -> BOM layered cost -> MOQ prices).
	"Item": {
		"validate": "lumirise_custom.costing.item_validate",
		# Item cost changed -> auto-refresh every BOM that uses it.
		"on_update": "lumirise_custom.costing.item_on_update",
	},
	# Production posted -> auto-refresh produced/consumed item BOM costs +
	# advance the material-flow handoff chain (issue -> receive -> transfer ->
	# produce -> dispatch FG) by raising the next team's task.
	"Stock Entry": {
		# Stamp the shop-floor issue type when the SE comes from a (non-Delivery) Pick
		# List — authoritative server-side mirror of the public/js/stock_entry.js default.
		"before_validate": "lumirise_custom.stores.set_shopfloor_issue_type",
		# Stamp the SO/Indent/WO/PO traceability panel from the SE's Work Order.
		"validate": "lumirise_custom.traceability.stamp",
		"on_submit": [
			"lumirise_custom.costing.on_stock_entry",
			"lumirise_custom.task_engine.on_stock_entry_submit",
		],
	},
	# Production Material Requisition raised -> task Stores to pick & issue.
	"Material Request": {
		"on_submit": "lumirise_custom.task_engine.on_material_request_submit",
	},
	# Pick List created -> pick & stage task for the relevant store.
	"Pick List": {
		"after_insert": "lumirise_custom.stores.on_pick_list_insert",
	},
	# Work Order drives the SO production status + a per-WO build task.
	"Work Order": {
		# Stamp the SO/Indent/WO/PO traceability panel (fail-safe).
		"validate": "lumirise_custom.traceability.stamp",
		"on_submit": [
			"lumirise_custom.status_sync.on_work_order_submit",
			"lumirise_custom.task_engine.on_work_order_submit",
			# Lock the BOM the floor is now building from.
			"lumirise_custom.bom_lock.lock_bom_on_work_order",
		],
		"on_update": "lumirise_custom.status_sync.on_work_order_update",
	},
	"BOM": {
		"validate": [
			"lumirise_custom.costing.bom_validate",
			# Keep a locked, live BOM from changing outside a BOM Change Request.
			"lumirise_custom.bom_lock.guard_bom_change",
		],
		"on_update_after_submit": [
			"lumirise_custom.costing.bom_on_update_after_submit",
			# A submitted BOM's is_active/is_default toggles run here, not validate.
			"lumirise_custom.bom_lock.guard_bom_change",
		],
	},
	# ---- Task / Notification / Kanban engine (auto-create operational cards) ----
	"Sales Order": {
		# SO approved -> hand off to Planning.
		"on_update": "lumirise_custom.task_engine.on_sales_order_update",
		"validate": [
			# Stamp the traceability panel (Indent/WO/PO fill in once Planning posts;
			# traceability.restamp refreshes the SO at that point).
			"lumirise_custom.traceability.stamp",
			# Annotate PO-match status vs the customer PO + source Quotation (WP-1.4).
			"lumirise_custom.sales_po_match.validate_po_match",
		],
	},
	"Material Planning": {
		"on_submit": [
			# Plan posted -> Indent to Purchase + Work Orders to Production.
			"lumirise_custom.task_engine.on_material_planning_submit",
			# Plan posted -> SO planning=Planned, purchase=Indented.
			"lumirise_custom.status_sync.on_material_planning_submit",
		],
	},
	"Indent": {
		# Indent fully approved -> Purchase raises the PO.
		"on_update": "lumirise_custom.task_engine.on_indent_update",
		"on_update_after_submit": "lumirise_custom.task_engine.on_indent_update",
		"validate": "lumirise_custom.traceability.stamp",
	},
	"IQC": {
		# Rejection at incoming QC -> Defect card to Purchase (vendor claim).
		"on_submit": "lumirise_custom.task_engine.on_iqc_submit",
		"validate": "lumirise_custom.traceability.stamp",
	},
	"Customer PDI": {
		# Pre-dispatch inspection failed -> Rework card to Production.
		"on_submit": "lumirise_custom.task_engine.on_customer_pdi_submit",
		"validate": "lumirise_custom.traceability.stamp",
	},
	# Inbound-chain custom doctypes: stamp the panel from their Purchase Order.
	"Vendor PDI": {
		"validate": "lumirise_custom.traceability.stamp",
	},
	"Inbound Logistics": {
		"validate": "lumirise_custom.traceability.stamp",
	},
	# Accountable material issue: stamp the panel from its Work Order.
	"Material Receipt": {
		"validate": "lumirise_custom.traceability.stamp",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		# Price sheets pending approval past their window flip to Expired.
		"lumirise_custom.lumirise_custom.doctype.price_sheet.price_sheet.expire_pending_sheets",
		# Overdue Lumirise Tasks -> escalate to the HOD (missed-deadline alert).
		"lumirise_custom.task_engine.escalate_overdue_tasks",
		# RM sitting in the rejection warehouse past the hold window -> one deduped
		# task to Stores (never auto-scraps; disposition stays with Praveen + Quality).
		"lumirise_custom.stores.flag_overdue_rm_rejections",
		# Daily self-test: verify the whole flow, pinpoint what broke + the fix,
		# and push an in-ERP digest. Read-only on prod; synthetic tier on a test
		# site only (gated). Runs last so the digest reflects the same-day escalation.
		"lumirise_custom.health_check.run_daily_health_check",
	],
}

# scheduler_events = {
# 	"all": [
# 		"lumirise_custom.tasks.all"
# 	],
# 	"daily": [
# 		"lumirise_custom.tasks.daily"
# 	],
# 	"hourly": [
# 		"lumirise_custom.tasks.hourly"
# 	],
# 	"weekly": [
# 		"lumirise_custom.tasks.weekly"
# 	],
# 	"monthly": [
# 		"lumirise_custom.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "lumirise_custom.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "lumirise_custom.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "lumirise_custom.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "lumirise_custom.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["lumirise_custom.utils.before_request"]
# after_request = ["lumirise_custom.utils.after_request"]

# Job Events
# ----------
# before_job = ["lumirise_custom.utils.before_job"]
# after_job = ["lumirise_custom.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"lumirise_custom.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

