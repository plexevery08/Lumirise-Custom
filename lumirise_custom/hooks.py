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

# Ship the Lumirise customisations as fixtures (ordered: states before workflow).
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Lumirise Custom"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "Lumirise Custom"]]},
	{"dt": "Workflow State", "filters": [["name", "in", [
		"Pending Purchase Manager", "Pending MD", "Approved", "Rejected", "Ordered"]]]},
	{"dt": "Workflow Action Master", "filters": [["name", "in", [
		"Submit for Approval", "Purchase Manager Approve", "MD Approve", "Reject"]]]},
	{"dt": "Workflow", "filters": [["name", "in", ["Indent Approval"]]]},
	{"dt": "Workspace", "filters": [["module", "=", "Lumirise Custom"]]},
]

# Focus 9 quality gates on standard ERPNext documents.
doc_events = {
	"Purchase Receipt": {
		"before_submit": "lumirise_custom.events.iqc_gate",
	},
	"Delivery Note": {
		"before_submit": "lumirise_custom.events.customer_pdi_gate",
	},
}

# Scheduled Tasks
# ---------------

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

