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
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Scan RM Package"), () => {
				frappe.prompt(
					[{ fieldname: "package_barcode", label: __("Package Barcode"), fieldtype: "Data", reqd: 1 }],
					(v) => frappe.call({
						method: "lumirise_custom.rm_barcode.get_package_scan_context",
						args: v,
					}).then(async (r) => {
						let p = r.message;
						const row = (frm.doc.items || []).find((d) =>
							d.item_code === p.item_code && d.s_warehouse === p.current_warehouse && !d.lr_rm_package
						);
						if (!row) {
							frappe.throw(__("No unscanned row for item {0} from {1}.", [p.item_code, p.current_warehouse]));
						}
						const requested = flt(row.qty);
						let scanned = Math.min(requested, flt(p.remaining_qty));
						if (scanned < flt(p.remaining_qty)) {
							const split = await frappe.call({
								method: "lumirise_custom.rm_barcode.split_package_for_issue",
								args: { package_barcode: p.barcode, qty: scanned },
								freeze: true,
								freeze_message: __("Creating partial-pick package…"),
							});
							p = split.message.package;
							frappe.msgprint(__("Partial pick created {0}. Print and attach this new label to the issued material.", [p.name]));
							frappe.utils.print("RM Receiving Package", p.name, "Lumirise RM Package Label", false);
						}
						if (requested > scanned) {
							const remainder = frm.add_child("items");
							["item_code", "item_name", "s_warehouse", "t_warehouse", "uom", "stock_uom", "conversion_factor"].forEach((f) => {
								remainder[f] = row[f];
							});
							remainder.qty = requested - scanned;
						}
						frappe.model.set_value(row.doctype, row.name, "qty", scanned);
						frappe.model.set_value(row.doctype, row.name, "lr_rm_package", p.name);
						frappe.model.set_value(row.doctype, row.name, "batch_no", p.batch_no);
						frappe.model.set_value(row.doctype, row.name, "use_serial_batch_fields", p.batch_no ? 1 : 0);
						frm.refresh_field("items");
						frappe.show_alert({ message: __("Scanned {0}: {1} {2}", [p.name, scanned, p.uom || ""]), indicator: "green" });
					}),
					__("Scan RM Package"),
					__("Apply")
				);
			}, __("Barcode"));
		}
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
