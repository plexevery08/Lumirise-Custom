// Lumirise: start the inbound quality chain from a submitted Purchase Order.
frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Vendor PDI"), () => {
				frappe.model.open_mapped_doc({
					method: "lumirise_custom.chain.make_vendor_pdi",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});
