// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lumirise Job Card", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.work_order) {
			frm.add_custom_button(__("Fetch Produced from Work Order"), () => {
				frappe.call({
					method: "lumirise_custom.lumirise_custom.doctype.lumirise_job_card.lumirise_job_card.fetch_produced_from_wo",
					args: { docname: frm.doc.name },
					freeze: true,
				}).then((r) => {
					frm.reload_doc();
					if (r && r.message) {
						frappe.show_alert({
							message: __("Produced {0} — {1}", [r.message.produced_qty, r.message.status]),
							indicator: r.message.status === "Missed" ? "red" : "green",
						});
					}
				});
			});
		}
		if (frm.doc.docstatus === 1 && frm.doc.status === "Missed") {
			frm.set_intro(__("Target missed by {0} — an escalation task was raised to Production.", [Math.abs(frm.doc.variance)]), "red");
		}
	},

	work_order(frm) {
		// Default the FG item + a target from the Work Order when one is linked.
		if (frm.doc.work_order) {
			frappe.db.get_value("Work Order", frm.doc.work_order, ["production_item", "qty"]).then((r) => {
				if (r && r.message) {
					if (!frm.doc.fg_item) frm.set_value("fg_item", r.message.production_item);
					if (!frm.doc.target_qty) frm.set_value("target_qty", r.message.qty);
				}
			});
		}
	},
});
