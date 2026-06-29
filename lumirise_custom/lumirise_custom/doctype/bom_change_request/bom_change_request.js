// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

const BCR = "lumirise_custom.lumirise_custom.doctype.bom_change_request.bom_change_request.";

function bcr_call(frm, method, args) {
	frappe.call({
		method: BCR + method,
		args: Object.assign({ docname: frm.doc.name }, args || {}),
		freeze: true,
	}).then((r) => {
		frm.reload_doc();
		if (r && r.message) {
			frappe.show_alert({ message: __("Done"), indicator: "green" });
		}
	});
}

frappe.ui.form.on("BOM Change Request", {
	fg_item(frm) {
		if (frm.doc.fg_item && !frm.doc.current_bom) {
			frappe.db.get_value("Item", frm.doc.fg_item, "default_bom").then((r) => {
				if (r && r.message && r.message.default_bom) {
					frm.set_value("current_bom", r.message.default_bom);
				}
			});
		}
	},

	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) {
			return;
		}
		const state = frm.doc.workflow_state;

		if (state === "Pending Change Approval") {
			frm.set_intro(__("Awaiting Vijay's approval of the change."), "orange");
			frm.add_custom_button(__("Approve Change (Vijay)"), () =>
				bcr_call(frm, "approve_change")
			).addClass("btn-primary");
		} else if (state === "Pending Cost Approval") {
			frm.set_intro(__("Change approved. Awaiting Ajay's cost approval — this creates the new BOM version."), "blue");
			frm.add_custom_button(__("Approve Cost & Create Version (Ajay)"), () =>
				bcr_call(frm, "approve_cost")
			).addClass("btn-primary");
		} else if (state === "Approved") {
			frm.set_intro(__("Approved. New BOM version: {0}", [frm.doc.new_bom || "—"]), "green");
			if (frm.doc.new_bom) {
				frm.add_custom_button(__("Open New BOM"), () =>
					frappe.set_route("Form", "BOM", frm.doc.new_bom)
				);
			}
		} else if (state === "Rejected") {
			frm.set_intro(__("Rejected."), "red");
		}

		if (["Pending Change Approval", "Pending Cost Approval"].includes(state)) {
			frm.add_custom_button(__("Reject"), () =>
				frappe.prompt(
					[{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 }],
					(v) => bcr_call(frm, "reject", { reason: v.reason }),
					__("Reject Change Request")
				)
			);
		}
	},
});
