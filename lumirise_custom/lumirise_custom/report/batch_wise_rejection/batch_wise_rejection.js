// Batch Wise Rejection — GRN / production / IQC rejections, batch-wise.
frappe.query_reports["Batch Wise Rejection"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "batch_no", label: __("Batch"), fieldtype: "Link", options: "Batch" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "rejected_qty" && data.rejected_qty > 0) {
			value = `<span style="color:var(--red-500);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
