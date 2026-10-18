frappe.ui.form.on("Sales Platform Settings", {
	refresh(frm) {
		if (!frappe.user_roles.includes("System Manager")) return;
		frm.add_custom_button(__("Rebuild All Costing"), async () => {
			await frappe.call({
				method: "lumirise_custom.costing.request_costing_rebuild",
				freeze: true,
				freeze_message: __("Queueing the item and BOM costing rebuild..."),
			});
			frappe.show_alert({ message: __("Costing rebuild queued"), indicator: "green" });
		});
	},
});
