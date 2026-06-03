// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

frappe.ui.form.on("Inbound Logistics", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("IQC"), () => {
				frappe.model.open_mapped_doc({
					method: "lumirise_custom.chain.make_iqc",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});
