// Material Request: when the parent "Main / FG Item" (fg_item) is chosen, auto-select
// that item's current latest active BOM into the parent BOM field (bom_no).
// "Latest version" = the most recently created active BOM for the item. bom_no stays
// editable so it can be overridden.
frappe.ui.form.on("Material Request", {
	fg_item(frm) {
		if (!frm.doc.fg_item) {
			frm.set_value("bom_no", null);
			return;
		}
		frappe.db
			.get_list("BOM", {
				filters: { item: frm.doc.fg_item, is_active: 1 },
				fields: ["name"],
				order_by: "creation desc",
				limit: 1,
			})
			.then((rows) => {
				frm.set_value("bom_no", rows && rows.length ? rows[0].name : null);
			});
	},
});
