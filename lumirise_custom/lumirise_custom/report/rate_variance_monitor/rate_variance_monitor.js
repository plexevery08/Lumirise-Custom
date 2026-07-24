// Rate Variance Monitor — red when the actual rate exceeds the costed rate
// (Phase-2 point 26: "if exceeded, red colour need to be displayed").
frappe.query_reports["Rate Variance Monitor"] = {
	filters: [
		{
			fieldname: "view",
			label: __("View"),
			fieldtype: "Select",
			options: "Both\nFinished Goods\nRaw Materials",
			default: "Both",
		},
		{
			fieldname: "exceeded_only",
			label: __("Exceeded Only"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "with_actuals_only",
			label: __("Only Items With Actuals"),
			fieldtype: "Check",
			default: 1,
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.exceeded && ["actual_rate", "variance", "variance_pct", "item_code"].includes(column.fieldname)) {
			value = `<span style="color:var(--red-500);font-weight:600">${value}</span>`;
		}
		if (!data.exceeded && column.fieldname === "variance" && data.costing_rate) {
			value = `<span style="color:var(--green-600)">${value}</span>`;
		}
		return value;
	},
};
