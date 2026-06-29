// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

frappe.query_reports["RM Rejection Ageing"] = {
	filters: [
		{
			fieldname: "warehouse",
			label: __("Rejection Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			description: __("Defaults to the RM Rejection warehouse from Operations Settings."),
		},
		{
			fieldname: "hold_days",
			label: __("Hold Window (days)"),
			fieldtype: "Int",
			default: 30,
			description: __("Anything held this long or longer is flagged 'Scrap due'."),
		},
	],
};
