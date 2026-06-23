// Material Receipt Stock Analysis — filters for the RM hand-off stock view.
frappe.query_reports["Material Receipt Stock Analysis"] = {
	filters: [
		{ fieldname: "material_receipt", label: __("Material Receipt"), fieldtype: "Link",
		  options: "Material Receipt" },
		{ fieldname: "work_order", label: __("Work Order"), fieldtype: "Link",
		  options: "Work Order" },
		{ fieldname: "source_stock_entry", label: __("Source Issue (Stock Entry)"),
		  fieldtype: "Link", options: "Stock Entry" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "from_date", label: __("From Receipt Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Receipt Date"), fieldtype: "Date" },
		{ fieldname: "only_shortfalls", label: __("Only Shortfalls"), fieldtype: "Check" },
		{ fieldname: "include_draft", label: __("Include Draft (unsubmitted)"),
		  fieldtype: "Check" },
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Flag any line where the factory accepted less than was issued.
		if (column.fieldname === "shortfall_qty" && data && flt(data.shortfall_qty) > 0) {
			value = `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
