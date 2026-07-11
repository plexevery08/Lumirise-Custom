// Lumirise 19.1 — default the Delivery Note source warehouse to Dispatch FG on a
// new DN. Dispatch always ships finished goods out of the Dispatch FG store, so the
// header Source Warehouse (which cascades to every item row via ERPNext's built-in
// autofill_warehouse) should be pre-selected. The value is resolved dynamically from
// Operations Settings (Rule 3 — never a hard-coded default).
//
// Two cases:
//   * Blank new DN  — fill Source Warehouse only if the user hasn't picked one.
//   * Created FROM a Sales Order — get_mapped_doc auto-copies the SO's set_warehouse
//     and each SO item's warehouse onto the DN, so a plain "fill if blank" misses it.
//     Dispatch always ships from Dispatch FG, so we OVERRIDE the inherited warehouse
//     (header + all rows) to Dispatch FG. We apply this once per form load so a manual
//     change the user makes afterwards is never clobbered on a re-render.
frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (!frm.is_new()) return;
		if (frm.__lumirise_dispatch_wh_applied) return;

		const from_so = (frm.doc.items || []).some((r) => r.against_sales_order);
		// Nothing to override yet on a truly empty manual DN with a warehouse already set.
		if (!from_so && frm.doc.set_warehouse) return;

		frappe.call({ method: "lumirise_custom.defaults.form_warehouse_defaults" }).then((r) => {
			const wh = (r && r.message) || {};
			if (!wh.dispatch_fg) return;

			if (from_so) {
				// Override the SO-inherited warehouse. Setting set_warehouse triggers
				// ERPNext's set_warehouse handler, which cascades to every item row.
				frm.set_value("set_warehouse", wh.dispatch_fg);
				frm.__lumirise_dispatch_wh_applied = true;
			} else if (!frm.doc.set_warehouse) {
				frm.set_value("set_warehouse", wh.dispatch_fg);
				frm.__lumirise_dispatch_wh_applied = true;
			}
		});
	},
});


// WP-3.4 — Packing approval: a Factory Store Manager signs off packing on a draft
// Delivery Note. The gate (before_submit) enforces it only when require_packing_approval
// is ON. Separate handler because the block above early-returns on non-new forms.
frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new() && !frm.doc.lr_packing_approved) {
			frm.add_custom_button(__("Approve Packing"), () => {
				frappe.call({
					method: "lumirise_custom.events.approve_packing",
					args: { delivery_note: frm.doc.name },
					callback: () => frm.reload_doc(),
				});
			}, __("Actions"));
		}
	},
});
