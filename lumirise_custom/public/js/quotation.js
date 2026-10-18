frappe.ui.form.on("Quotation", {
	refresh(frm) {
		const price_sheet = frm.doc.lr_price_sheet || frm.doc.custom_price_sheet;
		if (!price_sheet) return;
		frm.add_custom_button(__("Open Price Sheet"), () => {
			frappe.set_route("Form", "Price Sheet", price_sheet);
		});
		frm.set_intro(__("Created from approved Price Sheet {0}.", [price_sheet]), "blue");
	},
});
