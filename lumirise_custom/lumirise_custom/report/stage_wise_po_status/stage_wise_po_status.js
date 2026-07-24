frappe.query_reports["Stage-wise PO Status"] = {
	filters: [
		{ fieldname: "view", label: __("View"), fieldtype: "Select",
		  options: ["PO Summary", "Item Detail"], default: "PO Summary" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "stage", label: __("Current Stage"), fieldtype: "Select",
		  options: ["", "Ordered", "Vendor PDI", "In Transit", "IQC", "Received", "Billed", "Completed"] },
		{ fieldname: "include_closed", label: __("Include Closed / Completed POs"), fieldtype: "Check", default: 0 },
	],
};
