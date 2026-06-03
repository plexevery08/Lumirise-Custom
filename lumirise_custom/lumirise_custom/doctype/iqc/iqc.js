// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

frappe.ui.form.on("IQC", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.result !== "Rejected") {
			frm.add_custom_button(__("GRN (Purchase Receipt)"), () => {
				frappe.model.open_mapped_doc({
					method: "lumirise_custom.chain.make_grn",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});
