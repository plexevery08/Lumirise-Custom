// PO Stage Status — one row per PO line, staged Vendor → PDI → Transit → IQC → GRN.
frappe.query_reports["PO Stage Status"] = {
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
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "purchase_order", label: __("Purchase Order"), fieldtype: "Link", options: "Purchase Order" },
		{ fieldname: "include_closed", label: __("Include Closed / Completed"), fieldtype: "Check", default: 0 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "stage") {
			const colors = {
				"Received": "var(--green-600)",
				"At IQC / Reached": "var(--blue-500)",
				"In Transit": "var(--orange-500)",
				"At Vendor PDI": "var(--yellow-600)",
				"With Vendor": "var(--red-500)",
			};
			value = `<span style="color:${colors[data.stage] || "inherit"};font-weight:600">${value}</span>`;
		}
		return value;
	},
};
