"""Custom fields for BOM version-locking + change-request traceability.

Adds, on the standard BOM:
  - lr_locked         a BOM with an open Work Order is locked (floor can't build
                      off a moving target); changes must go via a BOM Change Request.
  - lr_version_date   the date this version became effective (auto date-versioning).
  - lr_supersedes     the previous BOM this version replaced.
  - lr_change_request the BOM Change Request that produced this version.
Tagged to the Lumirise Custom module so they ship in the Custom Field fixtures.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

BOM_FIELDS = [
	dict(
		fieldname="lr_version_sb",
		label="Lumirise Version Control",
		fieldtype="Section Break",
		insert_after="company",
		module="Lumirise Custom",
		collapsible=1,
	),
	dict(
		fieldname="lr_locked",
		label="Locked (open Work Order)",
		fieldtype="Check",
		insert_after="lr_version_sb",
		module="Lumirise Custom",
		read_only=1,
		description="Set automatically when a Work Order is raised against this BOM. "
		"Changes must go through a BOM Change Request.",
	),
	dict(
		fieldname="lr_version_date",
		label="Version Effective Date",
		fieldtype="Date",
		insert_after="lr_locked",
		module="Lumirise Custom",
		read_only=1,
	),
	dict(
		fieldname="lr_version_col",
		fieldtype="Column Break",
		insert_after="lr_version_date",
		module="Lumirise Custom",
	),
	dict(
		fieldname="lr_supersedes",
		label="Supersedes BOM",
		fieldtype="Link",
		options="BOM",
		insert_after="lr_version_col",
		module="Lumirise Custom",
		read_only=1,
	),
	dict(
		fieldname="lr_change_request",
		label="From Change Request",
		fieldtype="Link",
		options="BOM Change Request",
		insert_after="lr_supersedes",
		module="Lumirise Custom",
		read_only=1,
	),
]


def create_bom_fields():
	create_custom_fields({"BOM": BOM_FIELDS}, update=True)
