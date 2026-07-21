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

// Live shortfall = issued - received, recomputed the moment the factory edits the
// received qty in a row so the mismatch is visible before save. The controller's
// validate() recomputes the same on save and stays the source of truth.
frappe.ui.form.on("Material Receipt Item", {
	received_qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "shortfall_qty", flt(row.issued_qty) - flt(row.received_qty));
	},
});
