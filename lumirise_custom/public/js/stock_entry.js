// Lumirise: on a submitted "Material Issue to Shop Floor" stock entry, let the
// factory store manager raise a Material Receipt to acknowledge the hand-off
// (Ajay review 2026-06-14). Once acknowledged it is binding.
frappe.ui.form.on("Stock Entry", {
	// 14.1 — when Stores creates a Stock Entry from a (non-Delivery) Pick List, the
	// custom "Material Issue to Shop Floor" type should default automatically instead
	// of the operator hand-picking the newly-created type every time. That type maps to
	// the "Material Transfer" purpose (setup/production_setup.py), the same purpose a
	// material-transfer pick list already carries, so switching to it does not disturb
	// the warehouses/items the pick list mapped in.
	onload(frm) {
		if (!frm.is_new() || !frm.doc.pick_list) return;
		const ISSUE_TYPE = "Material Issue to Shop Floor";
		if (frm.doc.stock_entry_type === ISSUE_TYPE) return;
		// only override the generic default; never clobber a deliberately-chosen type
		// (e.g. "Material Transfer for Manufacture" line transfers).
		if (frm.doc.stock_entry_type && frm.doc.stock_entry_type !== "Material Transfer") return;
		frappe.db.get_value("Pick List", frm.doc.pick_list, "purpose").then((r) => {
			const purpose = r && r.message && r.message.purpose;
			if (purpose === "Delivery") return; // dispatch pick list — not a shop-floor issue
			frm.set_value("stock_entry_type", ISSUE_TYPE);
		});
	},

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
