frappe.ui.form.on("Warehouse", {
	refresh(frm) {
		if (!frm.is_new() && !frm.doc.is_group) {
			frm.add_custom_button(__("Print RM Location Label"), () => {
				frappe.utils.print(frm.doctype, frm.doc.name, "Lumirise RM Location Label", false);
			}, __("Barcode"));
		}
	},
});
