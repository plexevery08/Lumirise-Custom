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

const SAMPLE_METHOD = "lumirise_custom.samples.";

function sample_run(frm, method, args, freeze_message) {
	return frappe
		.call({
			method: SAMPLE_METHOD + method,
			args: args,
			freeze: true,
			freeze_message: freeze_message || __("Working…"),
		})
		.then((r) => {
			frm.reload_doc();
			if (r && r.message) {
				frappe.show_alert({ message: __("Done"), indicator: "green" });
			}
		});
}

function issue_sample_prompt(frm) {
	const item_codes = [...new Set((frm.doc.items || []).map((r) => r.item_code).filter(Boolean))];
	if (!item_codes.length) {
		frappe.msgprint(__("Add the IQC item lines first — samples are drawn against them."));
		return;
	}
	frappe.prompt(
		[
			{ fieldname: "item_code", label: __("Item"), fieldtype: "Select", options: item_codes.join("\n"), reqd: 1, default: item_codes[0] },
			{ fieldname: "sample_qty", label: __("Sample Qty"), fieldtype: "Float", reqd: 1 },
			{ fieldname: "taken_by", label: __("Taken By"), fieldtype: "Link", options: "User", reqd: 1, default: frappe.session.user },
			{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" },
		],
		(v) =>
			sample_run(
				frm,
				"issue_sample",
				{ docname: frm.doc.name, item_code: v.item_code, sample_qty: v.sample_qty, taken_by: v.taken_by, remarks: v.remarks },
				__("Recording sample…")
			),
		__("Issue Sample (pre-GRN)"),
		__("Record")
	);
}

function return_sample_prompt(frm) {
	const open = (frm.doc.sample_items || []).filter((r) => r.status !== "Returned");
	if (!open.length) {
		frappe.msgprint(__("No open samples to return."));
		return;
	}
	const options = open.map((r) => `${r.name} — ${r.item_code} · ${r.sample_qty} ${r.uom || ""} · ${r.taken_by || ""} [${r.status}]`);
	const by_label = {};
	open.forEach((r, i) => (by_label[options[i]] = r.name));
	frappe.prompt(
		[
			{ fieldname: "row", label: __("Sample"), fieldtype: "Select", options: options.join("\n"), reqd: 1, default: options[0] },
			{
				fieldname: "disposition",
				label: __("Disposition"),
				fieldtype: "Select",
				options: ["Returned Intact", "Built into Finished Unit", "Scrapped"].join("\n"),
				reqd: 1,
			},
		],
		(v) =>
			sample_run(
				frm,
				"return_sample",
				{ docname: frm.doc.name, row_name: by_label[v.row], disposition: v.disposition },
				__("Dispositioning sample…")
			),
		__("Return / Dispose Sample"),
		__("Post")
	);
}

function add_sample_buttons(frm) {
	if (frm.doc.docstatus === 2) {
		return; // cancelled
	}
	const status = frm.doc.status;
	// Issue is pre-GRN only (goods not owned until the GRN posts).
	if (!["Moved to RM", "Rejected"].includes(status)) {
		frm.add_custom_button(__("Issue Sample"), () => issue_sample_prompt(frm), __("Sample"));
	}
	// Return needs a logged sample; the disposition stock move requires the GRN
	// (server enforces "Moved to RM"), so only offer it once there is one to return.
	if ((frm.doc.sample_items || []).some((r) => r.status !== "Returned")) {
		frm.add_custom_button(__("Return Sample"), () => return_sample_prompt(frm), __("Sample"));
	}
}

frappe.ui.form.on("IQC", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		add_sample_buttons(frm);

		// Submitted: GRN is the next step (unless wholly rejected or already done).
		if (frm.doc.docstatus === 1) {
			if (frm.doc.status === "Moved to RM") {
				frm.set_intro(__("GRN posted — accepted stock is in the RM store."), "green");
			} else if ((frm.doc.items || []).some((r) => flt(r.accepted_qty) > 0)) {
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

		// AQL sampling plan: lot size -> Level I sample size + Accept/Reject per class.
		if (["IQC Received", "Testing"].includes(status)) {
			
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
