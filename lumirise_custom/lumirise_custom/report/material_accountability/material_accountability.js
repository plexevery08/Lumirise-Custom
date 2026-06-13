// Material Accountability — filters for the production balance view.
frappe.query_reports["Material Accountability"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		  default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "work_order", label: __("Work Order"), fieldtype: "Link", options: "Work Order" },
		{ fieldname: "production_item", label: __("FG Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "include_completed", label: __("Include Completed / Closed"), fieldtype: "Check" },
	],
};
