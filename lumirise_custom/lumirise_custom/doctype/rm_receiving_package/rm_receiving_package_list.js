frappe.listview_settings["RM Receiving Package"] = {
	onload(listview) {
		if (!frappe.user_roles.includes("System Manager")) return;
		listview.page.add_inner_button(__("Create Opening Stock Labels"), () => {
			frappe.prompt(
				[
					{
						fieldname: "item_code",
						label: __("Item"),
						fieldtype: "Link",
						options: "Item",
						reqd: 1,
					},
					{
						fieldname: "warehouse",
						label: __("Rack / Slot Warehouse"),
						fieldtype: "Link",
						options: "Warehouse",
						reqd: 1,
					},
					{
						fieldname: "batch_no",
						label: __("Existing Batch"),
						fieldtype: "Link",
						options: "Batch",
						reqd: 1,
					},
					{
						fieldname: "package_count",
						label: __("Physical Package Count"),
						fieldtype: "Int",
						reqd: 1,
					},
					{
						fieldname: "total_qty",
						label: __("Counted Total Qty"),
						fieldtype: "Float",
						reqd: 1,
					},
					{
						fieldname: "stock_reconciliation",
						label: __("Stock Reconciliation"),
						fieldtype: "Link",
						options: "Stock Reconciliation",
					},
				],
				(v) =>
					frappe
						.call({
							method: "lumirise_custom.rm_barcode.create_opening_packages",
							args: v,
							freeze: true,
							freeze_message: __("Creating opening stock labels…"),
						})
						.then((r) => {
							frappe.show_alert({
								message: __("Created {0} labels", [r.message.created.length]),
								indicator: "green",
							});
							listview.refresh();
						}),
				__("Opening Stock RM Packages"),
				__("Create Labels")
			);
		});
	},
};
