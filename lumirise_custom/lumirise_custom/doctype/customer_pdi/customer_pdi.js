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

// 18.3 — pre-fill the three warehouses on a NEW Customer PDI so the store/inspector
// sees them (and 18.2's "available in FG" can compute) BEFORE save. Dynamic values
// come from Operations Settings via the server helper — the same resolution the
// controller's validate() uses as a safety net; we only fill blanks, never overwrite.
function cpdi_prefill_warehouses(frm) {
	if (!frm.is_new()) return;
	if (frm.doc.source_warehouse && frm.doc.pdi_warehouse) return;
	frappe.call({ method: "lumirise_custom.defaults.form_warehouse_defaults" }).then((r) => {
		const wh = (r && r.message) || {};
		if (!frm.doc.source_warehouse && wh.dispatch_fg) {
			frm.set_value("source_warehouse", wh.dispatch_fg);
		}
		if (!frm.doc.pdi_warehouse && wh.pdi) {
			frm.set_value("pdi_warehouse", wh.pdi);
		}
		if (!frm.doc.rejection_warehouse && wh.rejection) {
			frm.set_value("rejection_warehouse", wh.rejection);
		}
	});
}

// Pull every stock FG line off the chosen Sales Order into the items grid. Only in
// Draft (the grid is locked afterwards); if rows already exist we confirm before
// replacing so a mis-click can't wipe the inspector's work.
function cpdi_fetch_so_items(frm) {
	if (!frm.doc.sales_order || frm.doc.status !== "Draft") return;
	const populate = () => {
		frappe.call({
			method: CPDI_METHOD + "fetch_sales_order_items",
			args: {
				sales_order: frm.doc.sales_order,
				source_warehouse: frm.doc.source_warehouse,
			},
			freeze: true,
			freeze_message: __("Fetching Sales Order items…"),
		}).then((r) => {
			const rows = (r && r.message) || [];
			frm.clear_table("items");
			rows.forEach((d) => Object.assign(frm.add_child("items"), d));
			frm.refresh_field("items");
			frappe.show_alert({
				message: rows.length
					? __("Fetched {0} item(s) from {1}", [rows.length, frm.doc.sales_order])
					: __("No stock items on {0}", [frm.doc.sales_order]),
				indicator: rows.length ? "green" : "orange",
			});
		});
	};
	if ((frm.doc.items || []).length) {
		frappe.confirm(
			__("Replace the current item rows with the items from {0}?", [frm.doc.sales_order]),
			populate
		);
	} else {
		populate();
	}
}

frappe.ui.form.on("Customer PDI", {
	setup(frm) {
		frm.set_query("fg_item", "items", () => ({ filters: { is_stock_item: 1 } }));
	},

	sales_order(frm) {
		cpdi_fetch_so_items(frm);
	},

	refresh(frm) {
		cpdi_set_grid_editable(frm);

		if (frm.is_new()) {
			cpdi_prefill_warehouses(frm);
			return;
		}

		const status = frm.doc.status;
		const is_store = cpdi_is_store(frm);

		// AQL sampling plan for the FG lot (how many of the batch to inspect).
		// HIDDEN 2026-07-07 at client request — inspection sampling flow not finalised
		// yet. Re-enable by uncommenting when the flow is defined (server method
		// lumirise_custom.quality.aql_for_lot is unchanged and still works).
		// frm.add_custom_button(__("AQL Sampling Plan"), () => {
		// 	const lot = (frm.doc.items || []).reduce((s, r) => s + (r.qty || 0), 0);
		// 	if (!lot) {
		// 		frappe.msgprint(__("Add the FG item rows (with qty) first."));
		// 		return;
		// 	}
		// 	frappe.call({
		// 		method: "lumirise_custom.quality.aql_for_lot",
		// 		args: { lot_size: lot, defect_class: "C" },
		// 		freeze: true,
		// 	}).then((r) => {
		// 		const promises = ["A", "B", "C"].map((c) =>
		// 			frappe.call({
		// 				method: "lumirise_custom.quality.aql_for_lot",
		// 				args: { lot_size: lot, defect_class: c },
		// 			})
		// 		);
		// 		Promise.all(promises).then((res) => {
		// 			const rows = res.map((x) => x.message).map(
		// 				(p) =>
		// 					`Class ${p.defect_class} · AQL ${p.aql} · inspect <b>${p.sample_size}</b> of ${p.lot_size}` +
		// 					` · Accept ≤${p.accept}, Reject ≥${p.reject}` +
		// 					(p.inspect_100pct ? " (100%)" : "")
		// 			);
		// 			frappe.msgprint({
		// 				title: __("AQL Sampling Plan (IS:2500, Level I)"),
		// 				message: rows.join("<br>") +
		// 					"<br><br><i>Verify Accept/Reject numbers against the IS:2500 master before vendor claims.</i>",
		// 				indicator: "blue",
		// 			});
		// 		});
		// 	});
		// });

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

// When the inspector picks an FG item on a row, pull its live on-hand in the FG
// (Dispatch FG) store into "Available in FG" straight away, before save. validate()
// still refreshes available_qty server-side on a Draft as the source of truth.
frappe.ui.form.on("Customer PDI Item", {
	fg_item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.fg_item) return;
		frappe.call({
			method: CPDI_METHOD + "fg_on_hand",
			args: { item_code: row.fg_item, warehouse: frm.doc.source_warehouse },
		}).then((r) => {
			frappe.model.set_value(cdt, cdn, "available_qty", flt((r && r.message) || 0));
		});
	},
});
