frappe.query_reports["Stock Variance Worklist"] = {
	filters: [
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "only_variance", label: __("Only Variances"), fieldtype: "Check", default: 1 },
		{ fieldname: "include_never_counted", label: __("Include Never-Counted"), fieldtype: "Check", default: 0 },
	],
};
