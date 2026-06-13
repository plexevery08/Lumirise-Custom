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

			// Pick List (Delivery) — pick FG from rack/bin for dispatch.
			frm.add_custom_button(__("Pick List (Dispatch)"), () => {
				frappe.call({
					method: "lumirise_custom.stores.make_delivery_pick_list",
					args: { sales_order: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating pick list..."),
					callback(r) {
						if (r.message) {
							frappe.set_route("Form", "Pick List", r.message.pick_list);
						}
					},
				});
			}, __("Create"));

			// Delivery Note (Dispatch) — partial/remaining qty carried automatically.
			// Blocked at submit until a passed Customer PDI exists for this SO.
			frm.add_custom_button(__("Delivery Note (Dispatch)"), () => {
				frappe.model.open_mapped_doc({
					method: "lumirise_custom.chain.make_delivery_note",
					frm: frm,
				});
			}, __("Create"));
		}
	},
});
