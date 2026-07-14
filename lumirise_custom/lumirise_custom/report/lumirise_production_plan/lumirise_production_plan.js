// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

frappe.query_reports["Lumirise Production Plan"] = {
	filters: [
		{ fieldname: "from_date", label: __("Production From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Production To"), fieldtype: "Date" },
		{ fieldname: "schedule", label: __("Schedule"), fieldtype: "Link", options: "Lumirise Production Schedule" },
		{ fieldname: "category", label: __("Category"), fieldtype: "Data" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "only_released", label: __("Only Released"), fieldtype: "Check" },
	],
};
