// Material Receipt — once the factory has acknowledged (submitted) the receipt,
// give a one-click jump to the Stock Analysis report filtered to this document so
// the user can immediately see accepted vs missing qty and stock on hand.
frappe.ui.form.on("Material Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Stock Analysis Report"), () => {
				frappe.set_route("query-report", "Material Receipt Stock Analysis", {
					material_receipt: frm.doc.name,
				});
			});
		}
	},
});
