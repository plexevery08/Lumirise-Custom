// Material Request — Requisition from BOM (Lumirise, Focus 9 flow).
//
// SINGLE owner of the fg_item / production_order / bom_no auto-fill so there is no
// cross-script race. (The old DB Client Script "Material Request - Requisition from BOM"
// used to also hook fg_item and fought this file, which made bom_no appear then clear.
// That Client Script is disabled; all of its logic lives here now.)
//
// Flow:
//   • Pick a Production Order (Work Order)  -> its FG item + Production Qty flow in,
//     and (because fg_item is set) the latest active BOM auto-fills.
//   • Or pick the Main / FG item directly    -> its latest active BOM auto-fills.
//   bom_no stays editable so it can be overridden, and "Get Items from BOM" explodes it.

function bom_filter(frm) {
	// Same filter the bom_no Link uses, so a fetched value is always accepted by the
	// field control (a value outside the Link's query gets auto-cleared by the client).
	return { item: frm.doc.fg_item, is_active: 1, docstatus: 1 };
}

async function fetch_latest_bom(frm) {
	// Use the product's DEFAULT BOM — the same source every other Lumirise path reads
	// (indent.py, material_planning.py, purchase_reco.py, the RM tracker). Reading
	// "most recently created" here instead made a Material Request explode a different
	// parts list than planning nets against (findings doc 2026-07-17, #3). The
	// BOM Change Request repoints default_bom on approval, so this stays in step.
	if (!frm.doc.fg_item) return null;
	const default_bom = await frappe.db.get_value("Item", frm.doc.fg_item, "default_bom");
	if (default_bom && default_bom.message && default_bom.message.default_bom) {
		return default_bom.message.default_bom;
	}
	// Fallback: FG item has no default_bom set — take the latest active submitted BOM.
	const rows = await frappe.db.get_list("BOM", {
		filters: bom_filter(frm),
		fields: ["name"],
		order_by: "creation desc",
		limit: 1,
	});
	return rows && rows.length ? rows[0].name : null;
}

frappe.ui.form.on("Material Request", {
	setup(frm) {
		frm.set_query("bom_no", () => ({ filters: bom_filter(frm) }));
		frm.set_query("production_order", () => ({ filters: { docstatus: 1 } }));
	},

	async production_order(frm) {
		if (!frm.doc.production_order) return;
		const wo = await frappe.db.get_doc("Work Order", frm.doc.production_order);
		// Set qty / type first; set fg_item LAST so its handler is the single, final
		// writer of bom_no — no second set_value racing behind it.
		frm.set_value("production_qty", wo.qty);
		if (!frm.doc.material_request_type) {
			frm.set_value("material_request_type", "Material Transfer");
		}
		await frm.set_value("fg_item", wo.production_item);
	},

	async fg_item(frm) {
		// One place sets bom_no. null clears it when there is no FG item / no active BOM.
		const bom = await fetch_latest_bom(frm);
		frm.set_value("bom_no", bom);
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;
		frm.add_custom_button(
			__("Get Items from BOM"),
			() => {
				if (!frm.doc.bom_no || !frm.doc.production_qty) {
					frappe.msgprint(__("Select the Main / FG Item, its BOM, and the Production Qty first."));
					return;
				}
				// get_bom_items returns each component already scaled to the Production Qty
				// (component-per-unit x production_qty), plus uom / stock_uom / conversion_factor / rate.
				frappe.call({
					method: "erpnext.manufacturing.doctype.bom.bom.get_bom_items",
					args: {
						bom: frm.doc.bom_no,
						company: frm.doc.company,
						qty: frm.doc.production_qty,
						fetch_exploded: 0,
					},
					freeze: true,
					freeze_message: __("Exploding BOM..."),
					callback(r) {
						if (!r.message || !r.message.length) {
							frappe.msgprint(__("No items returned for this BOM."));
							return;
						}
						const src = "Stores - L";
						const tgt = "Shopfloor Stock in Area - L";
						const sd =
							frm.doc.schedule_date ||
							frappe.datetime.add_days(frappe.datetime.nowdate(), 2);
						frm.clear_table("items");
						r.message.forEach((it) => {
							const cf = flt(it.conversion_factor) || 1;
							const uom = it.uom || it.stock_uom;
							const qty = flt(it.qty); // already BOM-qty x Production Qty
							frm.add_child("items", {
								item_code: it.item_code,
								item_name: it.item_name,
								description: it.description || it.item_name,
								qty: qty,
								uom: uom,
								stock_uom: it.stock_uom,
								conversion_factor: cf,
								stock_qty: qty * cf,
								rate: it.rate,
								schedule_date: sd,
								from_warehouse: src,
								warehouse: tgt,
							});
						});
						frm.refresh_field("items");
						frappe.show_alert({
							message: __("{0} components loaded from BOM (x {1} qty)", [
								r.message.length,
								frm.doc.production_qty,
							]),
							indicator: "green",
						});
					},
				});
			},
			__("Get Items")
		);
	},
});
