frappe.ui.form.on("RM Package", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Scan / Verify"), () => {
				frappe.call({
					method: "lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.scan_package",
					args: { barcode: frm.doc.package_barcode }, freeze: true,
				}).then(() => frappe.show_alert({ message: __("Package identity verified"), indicator: "green" }));
			}, __("Barcode"));
			if (frm.doc.status === "Available") {
				frm.add_custom_button(__("Put Away"), () => {
					frappe.prompt([{fieldname:"destination_warehouse", label:__("Destination Location"), fieldtype:"Link", options:"Warehouse", reqd:1}], (v) => {
						frappe.call({method:"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.put_away", args:{package:frm.doc.name, destination_warehouse:v.destination_warehouse}, freeze:true}).then(() => frm.reload_doc());
					}, __("Post Native Stock Transfer"), __("Put Away"));
				}, __("Stock"));
			}
		}
	}
});
