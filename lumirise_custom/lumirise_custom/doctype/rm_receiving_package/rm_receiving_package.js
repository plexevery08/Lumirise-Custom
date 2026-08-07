frappe.ui.form.on("RM Receiving Package", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Print Package Label"), () => {
				frappe.utils.print(frm.doctype, frm.doc.name, "Lumirise RM Package Label", false);
			});
			if (frm.doc.status === "Ready to Put Away") {
				frm.add_custom_button(__("Scan Rack & Put Away"), () => {
					frappe.prompt(
						[
							{
								fieldname: "location_barcode",
								label: __("Rack / Slot Barcode"),
								fieldtype: "Data",
								reqd: 1,
							},
						],
						(v) =>
							frappe
								.call({
									method: "lumirise_custom.rm_barcode.putaway_package",
									args: {
										package_barcode: frm.doc.barcode_value,
										location_barcode: v.location_barcode,
									},
									freeze: true,
									freeze_message: __("Posting put-away…"),
								})
								.then((r) => {
									frappe.show_alert({
										message: __("Put away in {0}", [r.message.location]),
										indicator: "green",
									});
									frm.reload_doc();
								}),
						__("Put Away RM Package"),
						__("Post Stock Transfer")
					);
				}).addClass("btn-primary");
			}
		}
	},
});
