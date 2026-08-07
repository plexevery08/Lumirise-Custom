frappe.query_reports["RM Slot Availability"] = {
	filters: [
		{
			fieldname: "slot_status",
			label: __("Slot Status"),
			fieldtype: "Select",
			options: "\nAvailable\nBlocked\nMaintenance",
		},
	],
};
