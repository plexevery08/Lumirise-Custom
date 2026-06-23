// Lumirise: on a submitted "Material Issue to Shop Floor" stock entry, let the
// factory store manager raise a Material Receipt to acknowledge the hand-off
// (Ajay review 2026-06-14). Once acknowledged it is binding.
frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.stock_entry_type === "Material Issue to Shop Floor") {
			frm.add_custom_button(__("Acknowledge Receipt (Material Receipt)"), () => {
				frappe.model.open_mapped_doc({
					method: "lumirise_custom.lumirise_custom.doctype.material_receipt.material_receipt.make_material_receipt",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});
