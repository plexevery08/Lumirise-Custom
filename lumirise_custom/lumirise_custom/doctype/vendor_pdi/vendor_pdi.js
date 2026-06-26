// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Vendor PDI cockpit — pre-dispatch inspection at the vendor.
// PDI Scheduled -> PDI In Progress -> PDI Passed -> Dispatched -> (submit) ->
// Create > Inbound Logistics. Each transition is a role-gated server method; the
// buttons only surface the right next action for the current state.

const VPDI_METHOD = "lumirise_custom.lumirise_custom.doctype.vendor_pdi.vendor_pdi.";

function vpdi_run(frm, method, args, freeze_message) {
	const call = () =>
		frappe
			.call({
				method: VPDI_METHOD + method,
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

function vpdi_set_grid_editable(frm) {
	const grid = frm.fields_dict.items.grid;
	const inspecting = frm.doc.status === "PDI In Progress";
	["approved_qty", "rejected_qty", "remarks"].forEach((f) =>
		grid.update_docfield_property(f, "read_only", inspecting ? 0 : 1)
	);
	grid.refresh();
}

frappe.ui.form.on("Vendor PDI", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		vpdi_set_grid_editable(frm);

		// Submitted: the consignment moves to Logistics (manual create).
		if (frm.doc.docstatus === 1) {
			if (frm.doc.status === "Dispatched") {
				frm.set_intro(__("Passed & dispatched. Raise Inbound Logistics to track it in transit."), "blue");
				frm.add_custom_button(__("Inbound Logistics"), () => {
					frappe.model.open_mapped_doc({
						method: "lumirise_custom.chain.make_inbound_logistics",
						frm: frm,
					});
				}, __("Create"));
			}
			return;
		}

		if (frm.doc.docstatus !== 0) {
			return; // cancelled
		}

		const status = frm.doc.status;

		if (status === "PDI Scheduled") {
			frm.set_intro(__("Inspection scheduled at the vendor. Start it to record results."), "blue");
			frm.add_custom_button(__("Start Inspection"), () =>
				vpdi_run(frm, "start_inspection", {}, __("Starting…"))
			).addClass("btn-primary");
		} else if (status === "PDI In Progress") {
			frm.set_intro(
				__("Enter each line's Accepted / Rejected qty, then record the result."),
				"orange"
			);
			frm.add_custom_button(__("Record Result"), () =>
				vpdi_run(frm, "record_result", {}, __("Recording…"))
			).addClass("btn-primary");
		} else if (status === "PDI Passed") {
			frm.set_intro(__("Inspection passed. Dispatch the accepted goods."), "green");
			frm.add_custom_button(__("Dispatch"), () =>
				vpdi_run(frm, "dispatch", {}, __("Dispatching…"))
			).addClass("btn-primary");
		} else if (status === "Dispatched") {
			frm.set_intro(__("Dispatched. Submit this Vendor PDI to raise Inbound Logistics."), "green");
		} else if (status === "Failed") {
			frm.set_intro(__("All qty rejected at inspection — nothing to dispatch."), "red");
		} else if (status === "On Hold") {
			frm.set_intro(__("On hold: {0}", [frm.doc.pdi_remarks || "—"]), "red");
			frm.add_custom_button(__("Resume Inspection"), () =>
				vpdi_run(frm, "start_inspection", {}, __("Resuming…"))
			);
		}

		// Park on hold from any open state.
		if (["PDI Scheduled", "PDI In Progress"].includes(status)) {
			frm.add_custom_button(__("Put On Hold"), () =>
				frappe.prompt(
					[{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 }],
					(v) => vpdi_run(frm, "hold", { reason: v.reason }, __("Holding…")),
					__("Put Vendor PDI On Hold")
				)
			);
		}
	},
});
