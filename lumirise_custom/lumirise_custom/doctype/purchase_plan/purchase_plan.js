// Purchase Plan -- merge indents → assign a vendor per line → split into one PO
// per vendor (Ajay review 2026-06-14).
frappe.ui.form.on("Purchase Plan", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.po_status !== "POs Created") {
			frm.add_custom_button(__("Create Purchase Orders (split by vendor)"), () => {
				frappe.call({
					method: "lumirise_custom.lumirise_custom.doctype.purchase_plan.purchase_plan.create_purchase_orders",
					args: { plan_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Splitting by vendor and creating Purchase Orders…"),
					callback(r) {
						const pos = r.message || [];
						if (!pos.length) return;
						frappe.msgprint({
							title: __("Purchase Orders created"),
							indicator: "green",
							message: __("Created {0} PO(s), one per vendor:", [pos.length])
								+ "<br>" + pos.map(
									(p) => `<a href="/app/purchase-order/${encodeURIComponent(p)}">${frappe.utils.escape_html(p)}</a>`
								).join("<br>"),
						});
						frm.reload_doc();
					},
				});
			}, __("Create"));
		}

		if (frm.doc.po_status === "POs Created") {
			frm.set_intro(
				__("Purchase Orders generated (one per vendor): {0}. Each awaits Purchase Head release.",
					[frm.doc.created_pos || ""]),
				"green"
			);
		}
	},
});
