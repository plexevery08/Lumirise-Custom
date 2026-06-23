// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Customer PDI cockpit — drives the FG -> PDI -> FG flow with store authorization.
// Every state-changing action is a server method (role + status gated there); the
// buttons below only surface the right action for the current state and user.

const CPDI_METHOD = "lumirise_custom.lumirise_custom.doctype.customer_pdi.customer_pdi.";

function cpdi_is_store(frm) {
	return (frappe.user_roles || []).some(
		(r) => r === "Factory Store Manager" || r === "System Manager"
	);
}

function cpdi_run(frm, method, args, freeze_message) {
	const call = () =>
		frappe
			.call({
				method: CPDI_METHOD + method,
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
	// Persist any in-form edits (e.g. the inspector's accepted/rejected qty) first.
	if (frm.is_dirty()) {
		return frm.save().then(call);
	}
	return call();
}

function cpdi_set_grid_editable(frm) {
	const grid = frm.fields_dict.items.grid;
	const draft = frm.doc.status === "Draft";
	const inspecting = frm.doc.status === "At PDI - Under Inspection";
	["fg_item", "qty"].forEach((f) =>
		grid.update_docfield_property(f, "read_only", draft ? 0 : 1)
	);
	["accepted_qty", "rejected_qty", "remarks"].forEach((f) =>
		grid.update_docfield_property(f, "read_only", inspecting ? 0 : 1)
	);
	grid.cannot_add_rows = !draft;
	if (grid.df) {
		grid.df.cannot_add_rows = !draft;
		grid.df.cannot_delete_rows = !draft;
	}
	grid.refresh();
}

frappe.ui.form.on("Customer PDI", {
	setup(frm) {
		frm.set_query("fg_item", "items", () => ({ filters: { is_stock_item: 1 } }));
	},

	refresh(frm) {
		cpdi_set_grid_editable(frm);

		if (frm.is_new()) {
			return;
		}

		const status = frm.doc.status;
		const is_store = cpdi_is_store(frm);

		// Links to the stock entries this PDI posted.
		// if (frm.doc.send_stock_entry) {
		// 	frm.add_custom_button(
		// 		__("Issue Entry"),
		// 		() => frappe.set_route("Form", "Stock Entry", frm.doc.send_stock_entry),
		// 		__("Stock Entries")
		// 	);
		// }
		// if (frm.doc.return_stock_entry) {
		// 	frm.add_custom_button(
		// 		__("Return Entry"),
		// 		() => frappe.set_route("Form", "Stock Entry", frm.doc.return_stock_entry),
		// 		__("Stock Entries")
		// 	);
		// }
		// if (frm.doc.rejection_stock_entry) {
		// 	frm.add_custom_button(
		// 		__("Rejection Entry"),
		// 		() => frappe.set_route("Form", "Stock Entry", frm.doc.rejection_stock_entry),
		// 		__("Stock Entries")
		// 	);
		// }

		if (frm.doc.docstatus !== 0) {
			return; // submitted / cancelled — flow is finished
		}

		if (status === "Draft") {
			frm.set_intro(
				__("Add the FG items and qty, then send the request to the store for authorization."),
				"blue"
			);
			frm.page.set_primary_action(__("Send for Store Authorization"), () =>
				cpdi_run(frm, "send_for_authorization", {}, __("Sending request…"))
			);
		} else if (status === "Pending Store Authorization") {
			if (is_store) {
				frm.set_intro(
					__("Authorize to move the boxes from the FG store into the Customer PDI store."),
					"orange"
				);
				frm.page.set_primary_action(__("Authorize & Issue to PDI"), () =>
					frappe.confirm(
						__("Move {0} item(s) from {1} to {2}?", [
							frm.doc.items.length,
							frm.doc.source_warehouse,
							frm.doc.pdi_warehouse,
						]),
						() => cpdi_run(frm, "authorize_send", {}, __("Issuing to PDI store…"))
					)
				);
				frm.add_custom_button(__("Reject Request"), () =>
					frappe.prompt(
						[{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 }],
						(v) => cpdi_run(frm, "reject_send", { reason: v.reason }, __("Rejecting…")),
						__("Reject PDI Issue Request")
					)
				);
			} else {
				frm.set_intro(__("Waiting for the store to authorize the issue to the PDI store."), "orange");
			}
		} else if (status === "At PDI - Under Inspection") {
			frm.set_intro(
				__("Boxes are in the PDI store. Record each item's accepted / rejected qty, then complete the inspection."),
				"blue"
			);
			frm.page.set_primary_action(__("Complete Inspection"), () =>
				cpdi_run(frm, "complete_inspection", {}, __("Completing inspection…"))
			);
		} else if (status === "Inspection Completed") {
			if (is_store) {
				frm.set_intro(
					__("Inspection done (sign-off: {0}). Authorize the return to send boxes back to the FG store.", [
						frm.doc.customer_signoff || "—",
					]),
					"orange"
				);
				frm.page.set_primary_action(__("Authorize Return to FG"), () =>
					cpdi_run(frm, "authorize_return", {}, __("Returning to FG store…"))
				);
			} else {
				frm.set_intro(__("Waiting for the store to authorize the return to the FG store."), "orange");
			}
		} else if (status === "Send Rejected") {
			frm.set_intro(
				__("The store rejected this request: {0}", [frm.doc.authorization_remarks || "—"]),
				"red"
			);
			frm.add_custom_button(__("Reopen as Draft"), () =>
				cpdi_run(frm, "reopen_as_draft", {}, __("Reopening…"))
			);
		}
	},
});
