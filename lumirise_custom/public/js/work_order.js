// Lumirise production cockpit on the Work Order form.
// One button per Focus 9 screen, in order, all line-aware. Native ERPNext stock
// mechanics underneath; the buttons drive the correct line warehouses + the
// Quality-gated rejection and FG-count-mismatch flows.
//
//   Create Pick List → Issue to Shop Floor → Transfer to Line → Receive FG
//                    → Reject from Line → Move to Dispatch FG
//
// Accountability indicators (Required / Issued to line / Produced / Balance) make
// the "issue partial, always see the remaining" requirement visible at a glance.

frappe.ui.form.on("Work Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		lumirise_accountability(frm);

		const grp = __("Production");
		const open = !["Completed", "Stopped", "Closed"].includes(frm.doc.status);

		// Production-INPUT steps (Pick List → Receive FG) show only while the order is
		// still open. The FG-handling buttons after this block (Reject finished units,
		// Move to Dispatch FG) stay available even when the WO is Completed/Closed —
		// dispatch and post-build rejection happen after production is done.
		if (open) {

		// 0) Pick List — pick the BOM materials from rack/bin for the line.
		frm.add_custom_button(__("Create Pick List"), () => {
			frappe.call({
				method: "lumirise_custom.stores.make_work_order_pick_list",
				args: { work_order: frm.doc.name },
				freeze: true,
				freeze_message: __("Creating pick list..."),
				callback(r) {
					if (r.message) frappe.set_route("Form", "Pick List", r.message.pick_list);
				},
			});
		}, grp);

		// 1) Issue material to the shop floor (RM Store → Shop Floor, partial OK).
		frm.add_custom_button(__("Issue to Shop Floor"), () => {
			const pending = flt(frm.doc.qty) - flt(frm.doc.material_transferred_for_manufacturing);
			frappe.prompt(
				[{ fieldname: "qty", label: __("Qty to issue"), fieldtype: "Float", reqd: 1, default: pending,
				   description: __("Partial issues are allowed — the balance stays visible on the order.") }],
				(v) => lumirise_call(frm, "issue_to_shop_floor", { work_order: frm.doc.name, qty: v.qty },
					__("Issuing to shop floor...")),
				__("Issue to Shop Floor"), __("Issue"));
		}, grp);

		// 2) Transfer to a specific line (Shop Floor → Line-N WIP).
		frm.add_custom_button(__("Transfer to Line"), () => {
			lumirise_with_lines((line_options) => {
				const pending = flt(frm.doc.qty) - flt(frm.doc.material_transferred_for_manufacturing);
				frappe.prompt(
					[
						{ fieldname: "line", label: __("Production Line"), fieldtype: "Link", options: "Warehouse", reqd: 1, get_query: () => ({ filters: [["Warehouse", "name", "in", line_options]] }) },
						{ fieldname: "qty", label: __("Qty to transfer"), fieldtype: "Float", reqd: 1, default: pending },
					],
					(v) => lumirise_call(frm, "transfer_to_line",
						{ work_order: frm.doc.name, line_warehouse: v.line, qty: v.qty },
						__("Transferring to {0}...", [v.line])),
					__("Transfer to Line"), __("Transfer"));
			});
		}, grp);

		// 3) Receive finished goods (Manufacture from the line) + physical-count check.
		frm.add_custom_button(__("Receive FG"), () => {
			lumirise_with_lines((line_options) => {
				const pending = flt(frm.doc.qty) - flt(frm.doc.produced_qty);
				frappe.prompt(
					[
						{ fieldname: "line", label: __("Production Line"), fieldtype: "Link", options: "Warehouse", reqd: 1, get_query: () => ({ filters: [["Warehouse", "name", "in", line_options]] }) },
						{ fieldname: "produced_qty", label: __("Produced Qty (system)"), fieldtype: "Float", reqd: 1, default: pending },
						{ fieldname: "physical_qty", label: __("Physical Count (boxes × pcs)"), fieldtype: "Float",
						  description: __("Leave blank if it matches. A difference raises a Stock-Mismatch task.") },
					],
					(v) => lumirise_call(frm, "receive_finished_goods",
						{ work_order: frm.doc.name, line_warehouse: v.line, produced_qty: v.produced_qty, physical_qty: v.physical_qty || null },
						__("Posting finished goods..."), (r) => r.message && r.message.mismatch
							? __("FG posted ({0}) — mismatch task raised.", [r.message.stock_entry])
							: __("FG posted: {0}", [r.message.stock_entry])),
					__("Receive Finished Goods"), __("Post"));
			});
		}, grp);
		} // end production-input steps (shown only while the order is open)

		// 4) Reject from production (Quality-gated draft transfer to the rejection store).
		frm.add_custom_button(__("Reject from Line"), () => {
			lumirise_with_lines((line_options) => {
				frappe.prompt(
					[
						{ fieldname: "line", label: __("Production Line"), fieldtype: "Link", options: "Warehouse", get_query: () => ({ filters: [["Warehouse", "name", "in", line_options]] }) },
						{ fieldname: "qty", label: __("Rejected Qty"), fieldtype: "Float", reqd: 1 },
						{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text" },
					],
					(v) => lumirise_call(frm, "reject_from_line",
						{ work_order: frm.doc.name, line_warehouse: v.line, qty: v.qty, reason: v.reason },
						__("Raising rejection for Quality approval..."),
						(r) => __("Draft rejection {0} sent to Quality.", [r.message.draft_stock_entry])),
					__("Reject from Production"), __("Submit to Quality"));
			});
		}, grp);

		// 5) Move finished goods Production FG → Dispatch FG.
		frm.add_custom_button(__("Move to Dispatch FG"), () => {
			frappe.prompt(
				[{ fieldname: "qty", label: __("Qty to move"), fieldtype: "Float",
				   description: __("Leave blank to move everything currently in the Production FG store.") }],
				(v) => lumirise_call(frm, "move_to_dispatch",
					{ work_order: frm.doc.name, qty: v.qty || null },
					__("Moving to Dispatch FG..."),
					(r) => __("Moved {0} to Dispatch FG.", [r.message.qty])),
				__("Move to Dispatch FG"), __("Move"));
		}, grp);
	},
});

// Required → Issued to line → Produced → Balance, as dashboard indicators.
function lumirise_accountability(frm) {
	const required = flt(frm.doc.qty);
	const issued = flt(frm.doc.material_transferred_for_manufacturing);
	const produced = flt(frm.doc.produced_qty);
	const bal_issue = required - issued;
	const bal_prod = required - produced;
	frm.dashboard.add_indicator(__("Required: {0}", [required]), "blue");
	frm.dashboard.add_indicator(__("Issued to line: {0}", [issued]), issued >= required ? "green" : "orange");
	frm.dashboard.add_indicator(__("Balance to issue: {0}", [bal_issue]), bal_issue <= 0 ? "green" : "orange");
	frm.dashboard.add_indicator(__("Produced: {0}", [produced]), produced >= required ? "green" : "blue");
	frm.dashboard.add_indicator(__("Balance to produce: {0}", [bal_prod]), bal_prod <= 0 ? "green" : "red");
}

// Fetch configured lines, then hand the list of line-warehouse names (array) to cb,
// used as the get_query filter for the "Production Line" Link fields in the dialogs.
function lumirise_with_lines(cb) {
	frappe.call({
		method: "lumirise_custom.production.get_production_lines",
		callback(r) {
			const lines = (r.message || []).map((l) => l.line_warehouse);
			if (!lines.length) {
				frappe.msgprint(__("No production lines configured. Add them under Lumirise Operations Settings → Production Lines."));
				return;
			}
			cb(lines);
		},
	});
}

// Thin wrapper: call a production.py method, toast the result, reload the WO.
function lumirise_call(frm, method, args, freeze_message, message_fn) {
	frappe.call({
		method: `lumirise_custom.production.${method}`,
		args,
		freeze: true,
		freeze_message,
		callback(r) {
			if (!r.message) return;
			const msg = message_fn ? message_fn(r) : __("Done.");
			frappe.show_alert({ message: msg, indicator: "green" });
			frm.reload_doc();
		},
	});
}
