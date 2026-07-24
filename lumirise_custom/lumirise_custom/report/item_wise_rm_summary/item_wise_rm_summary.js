frappe.query_reports["Item-wise RM Summary"] = {
	filters: [
		{ fieldname: "view", label: __("View"), fieldtype: "Select",
		  options: ["Summary by Item", "Line Detail"], default: "Summary by Item" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Select",
		  options: ["", "Raw Material", "LED Raw Material"] },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
	],
};
