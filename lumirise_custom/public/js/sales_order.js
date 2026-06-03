// Lumirise: raise a pre-dispatch Customer PDI from a submitted Sales Order.
frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Customer PDI"), () => {
				frappe.model.open_mapped_doc({
					method: "lumirise_custom.chain.make_customer_pdi",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});
