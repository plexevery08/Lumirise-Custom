// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

frappe.query_reports["Lumirise Daily Production and Packing"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{
			fieldname: "production_line", label: __("Line"), fieldtype: "Link", options: "Warehouse",
			get_query: () => ({ query: "lumirise_custom.queries.line_warehouse_query" }),
		},
		{ fieldname: "customer", label: __("Customer (Brand)"), fieldtype: "Link", options: "Customer" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.is_subtotal) {
			value = `<b>${value}</b>`;
		} else if (column.fieldname === "status") {
			const color = { "On Target": "green", Warning: "orange", Action: "red" }[value];
			if (color) value = `<span style="color:var(--text-on-${color}, ${color})">${value}</span>`;
		}
		return value;
	},
};
