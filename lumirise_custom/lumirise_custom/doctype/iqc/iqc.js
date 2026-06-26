// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// IQC cockpit — IQC Received -> Testing -> Passed -> (submit) -> GRN -> Moved to RM.
// Quality records the per-line accepted/rejected qty in the grid; the buttons drive
// the status. GRN is created MANUALLY via Create > GRN after the IQC is submitted.

const IQC_METHOD = "lumirise_custom.lumirise_custom.doctype.iqc.iqc.";

function iqc_run(frm, method, args, freeze_message) {
	const call = () =>
		frappe
			.call({
				method: IQC_METHOD + method,
				args: Object.assign({ docname: frm.doc.name }, args || {}),
				freeze: true,
				freeze_message: freeze_message || __("Working…"),
			})
			.then((r) => {
				frm.reload_doc();
				if (r && r.message) {
					frappe.show_alert({ message: __("Done"), indicator: "green" });
				}
			});
	// Persist the inspector's accepted/rejected qty edits first.
	if (frm.is_dirty()) {
		return frm.save().then(call);
	}
	return call();
}

frappe.ui.form.on("IQC", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		// Submitted: GRN is the next step (unless wholly rejected or already done).
		if (frm.doc.docstatus === 1) {
			if (frm.doc.status === "Moved to RM") {
				frm.set_intro(__("GRN posted — accepted stock is in the RM store."), "green");
			} else if (frm.doc.result !== "Rejected") {
				frm.set_intro(__("IQC passed. Raise the GRN to take the accepted stock into the RM store."), "blue");
				frm.add_custom_button(__("GRN (Purchase Receipt)"), () => {
					frappe.model.open_mapped_doc({
						method: "lumirise_custom.chain.make_grn",
						frm: frm,
					});
				}, __("Create"));
			} else {
				frm.set_intro(__("All qty rejected — no GRN can be raised."), "red");
			}
			return;
		}

		if (frm.doc.docstatus !== 0) {
			return; // cancelled
		}

		const status = frm.doc.status;

		if (status === "IQC Received") {
			frm.set_intro(__("Consignment received for inspection. Start testing."), "blue");
			frm.add_custom_button(__("Start Testing"), () =>
				iqc_run(frm, "start_testing", {}, __("Starting…"))
			).addClass("btn-primary");
		} else if (status === "Testing") {
			frm.set_intro(
				__("Under test. Enter each line's Accepted / Rejected qty (set a Disposition for rejects), then record the result."),
				"orange"
			);
			frm.add_custom_button(__("Record Result"), () =>
				iqc_run(frm, "record_result", {}, __("Recording result…"))
			).addClass("btn-primary");
		} else if (status === "Passed") {
			frm.set_intro(__("Inspection passed. Submit the IQC to unlock the GRN."), "green");
		} else if (status === "Rejected") {
			frm.set_intro(__("All qty rejected. Submit to record — no GRN will be allowed."), "red");
		} else if (status === "On Hold") {
			frm.set_intro(__("On hold: {0}", [frm.doc.iqc_remarks || "—"]), "red");
			frm.add_custom_button(__("Resume Testing"), () =>
				iqc_run(frm, "start_testing", {}, __("Resuming…"))
			);
		}

		// Park on hold from any open state.
		if (["IQC Received", "Testing"].includes(status)) {
			frm.add_custom_button(__("Put On Hold"), () =>
				frappe.prompt(
					[{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 }],
					(v) => iqc_run(frm, "hold", { reason: v.reason }, __("Holding…")),
					__("Put IQC On Hold")
				)
			);
		}
	},
});
