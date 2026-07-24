frappe.query_reports["Costing Rate Breach"] = {
	filters: [
		{ fieldname: "only_breaches", label: __("Only Breaches"), fieldtype: "Check", default: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "breach_pct") {
			const colour = data.indicator === "Red" ? "red" : data.indicator === "Amber" ? "orange" : "green";
			value = `<span style="color:${colour};font-weight:bold">${value}</span>`;
		}
		return value;
	},
};
