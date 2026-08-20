frappe.ui.form.on("RM Package", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(
			__("Scan / Verify"),
			() => {
				frappe
					.call({
						method:
							"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.scan_package",
						args: { barcode: frm.doc.package_barcode },
						freeze: true,
					})
					.then(() =>
						frappe.show_alert({ message: __("Package identity verified"), indicator: "green" })
					);
			},
			__("Barcode")
		);

		if (frm.doc.status === "Available" && !frm.doc.label_applied) {
			frm.add_custom_button(
				__("Print Label"),
				() => frappe.utils.print(frm.doctype, frm.doc.name, "RM Package Label"),
				__("Barcode")
			);
			frm.add_custom_button(
				__("Confirm Label Applied"),
				() =>
					frappe
						.call({
							method:
								"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.confirm_label_applied",
							args: { package: frm.doc.name },
							freeze: true,
							freeze_message: __("Recording physical label…"),
						})
						.then(() => frm.reload_doc()),
				__("Barcode")
			);
		}

		if (frm.doc.status === "Available" && frm.doc.label_applied) {
			frm.add_custom_button(
				__("Scan Rack & Put Away"),
				() => {
					frappe.prompt(
						[
							{
								fieldname: "destination_warehouse",
								label: __("Destination Location Barcode"),
								fieldtype: "Data",
								reqd: 1,
							},
						],
						(values) =>
							frappe
								.call({
									method:
										"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.put_away",
									args: {
										package: frm.doc.name,
										destination_warehouse: values.destination_warehouse,
									},
									freeze: true,
									freeze_message: __("Posting native stock transfer…"),
								})
								.then(() => frm.reload_doc()),
						__("Scan Destination Rack"),
						__("Put Away")
					);
				},
				__("Stock")
			);
		}
	},
});
