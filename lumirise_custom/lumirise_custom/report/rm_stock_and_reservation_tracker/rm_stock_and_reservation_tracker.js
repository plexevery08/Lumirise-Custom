// RM Stock & Reservation Tracker — full raw-material visibility in one screen.
frappe.query_reports["RM Stock and Reservation Tracker"] = {
	filters: [
		{
			fieldname: "view", label: __("View"), fieldtype: "Select",
			options: ["Summary by Item", "Reservation Detail (WO -> SO)", "Incoming Pipeline Detail"].join("\n"),
			default: "Summary by Item", reqd: 1,
		},
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		  default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "item_group", label: __("Item Group (RM)"), fieldtype: "Link", options: "Item Group",
		  get_query: () => ({ filters: { name: ["in", ["Raw Material", "LED Raw Material"]] } }) },
		{ fieldname: "warehouse", label: __("Warehouse (Summary)"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "work_order", label: __("Work Order"), fieldtype: "Link", options: "Work Order" },
		{ fieldname: "only_shortfall", label: __("Only Shortfalls (Summary)"), fieldtype: "Check" },
		{ fieldname: "include_zero", label: __("Include Zero-activity Items"), fieldtype: "Check" },
		{ fieldname: "include_completed", label: __("Include Completed WOs (Detail)"), fieldtype: "Check" },
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Highlight a real shortfall in red so the planner's eye lands on it.
		if (column.fieldname === "shortfall" && data && flt(data.shortfall) > 0) {
			value = `<span style="color:var(--red-600,#b91c1c);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
