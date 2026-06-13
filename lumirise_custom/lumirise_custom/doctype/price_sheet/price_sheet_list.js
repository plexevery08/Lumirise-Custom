frappe.listview_settings["Price Sheet"] = {
	add_fields: ["status", "valid_till"],
	get_indicator(doc) {
		const colors = {
			Draft: "gray",
			"Pending Approval": "orange",
			Approved: "green",
			Rejected: "red",
			Expired: "darkgrey",
		};
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
