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
		lumirise_render_line_transfer(frm);

		const grp = __("Production");
		const open = !["Completed", "Stopped", "Closed"].includes(frm.doc.status);

		// Production-INPUT steps (Pick List → Receive FG) show only while the order is
		// still open. The FG-handling buttons after this block (Reject finished units,
		// Move to Dispatch FG) stay available even when the WO is Completed/Closed —
		// dispatch and post-build rejection happen after production is done.
		if (open) {

		// 0) Pick List — pick the BOM materials from rack/bin for the line.
		// frm.add_custom_button(__("Create Pick List"), () => {
		// 	frappe.call({
		// 		method: "lumirise_custom.stores.make_work_order_pick_list",
		// 		args: { work_order: frm.doc.name },
		// 		freeze: true,
		// 		freeze_message: __("Creating pick list..."),
		// 		callback(r) {
		// 			if (r.message) frappe.set_route("Form", "Pick List", r.message.pick_list);
		// 		},
		// 	});
		// }, grp);

		// 1) Issue to Shop Floor is intentionally NOT here — the sanctioned flow is
		// Production raises a Material Request → Stores makes a Pick List → Stores
		// posts the "Material Issue to Shop Floor" Stock Entry. Keeping it off the Work
		// Order stops material being issued for the full WO qty instead of the qty the
		// Material Request actually asked for.

		// 2) Transfer to a specific line (Shop Floor → Line-N WIP). The qty defaults
		// from what is actually on the shop floor for this WO (what the Material Request
		// delivered), not the WO plan (change-list 16.1). The entry is created as a
		// DRAFT and we jump to it — the user reviews the component rows and warehouses,
		// then submits. transfer_to_line() caps the qty at both the WO pending and the
		// shop-floor stock, so the transferred-for-manufacture count can never inflate
		// (change-list 16.5/16.6).
		frm.add_custom_button(__("Transfer to Line"), () => {
			frappe.call({
				method: "lumirise_custom.production.shop_floor_available_qty",
				args: { work_order: frm.doc.name },
				callback(a) {
					const on_floor = flt(a.message);
					if (on_floor <= 0) {
						frappe.msgprint(__("Nothing is on the shop floor for this Work Order yet. Raise a Material Request and have Stores issue material to the shop floor first."));
						return;
					}
					lumirise_with_lines((line_options) => {
						frappe.prompt(
							[
								{ fieldname: "line", label: __("Production Line"), fieldtype: "Link", options: "Warehouse", reqd: 1, get_query: () => ({ filters: [["Warehouse", "name", "in", line_options]] }) },
								{ fieldname: "qty", label: __("Qty to transfer"), fieldtype: "Float", reqd: 1, default: on_floor,
								  description: __("On the shop floor now: {0} (what the Material Request delivered). Transfer up to this; raise another Material Request to send more.", [on_floor]) },
							],
							(v) => frappe.call({
								method: "lumirise_custom.production.transfer_to_line",
								args: { work_order: frm.doc.name, line_warehouse: v.line, qty: v.qty },
								freeze: true,
								freeze_message: __("Preparing draft transfer to {0}...", [v.line]),
								callback(r) {
									if (!r.message) return;
									frappe.show_alert({ message: __("Draft transfer {0} ready — review and submit it.", [r.message.stock_entry]), indicator: "blue" });
									frappe.set_route("Form", "Stock Entry", r.message.stock_entry);
								},
							}),
							__("Transfer to Line"), __("Prepare Draft"));
					});
				},
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

// Two distinct balances, so the WO plan and the shop-floor reality are never confused:
//   • Required / Transferred to line / Balance to produce  → against the WHOLE Work Order.
//   • On shop floor (available to transfer)                → what the Material Request has
//     actually delivered and is waiting to go to a line. This is why a WO built for 1000
//     can correctly show "500 still to produce" while only 50 is transferable right now —
//     the rest needs another Material Request.
function lumirise_accountability(frm) {
	const required = flt(frm.doc.qty);
	const issued = flt(frm.doc.material_transferred_for_manufacturing);
	const produced = flt(frm.doc.produced_qty);
	const bal_prod = required - produced;
	frm.dashboard.add_indicator(__("WO Required: {0}", [required]), "blue");
	frm.dashboard.add_indicator(__("Transferred to line: {0}", [issued]), issued >= required ? "green" : "orange");
	frm.dashboard.add_indicator(__("Produced: {0}", [produced]), produced >= required ? "green" : "blue");
	frm.dashboard.add_indicator(__("Balance to produce (WO): {0}", [bal_prod]), bal_prod <= 0 ? "green" : "red");

	// Shop-floor-bounded number — fetched live from stock (what the MR delivered).
	frappe.call({
		method: "lumirise_custom.production.shop_floor_available_qty",
		args: { work_order: frm.doc.name },
		callback(r) {
			const avail = flt(r.message);
			frm.dashboard.add_indicator(__("On shop floor — transferable now: {0}", [avail]), avail > 0 ? "orange" : "gray");
		},
	});
}

// Line Transfer tab — full per-line qty breakdown for this Work Order:
// where each unit went, what came back produced, what is still WIP on the line,
// and how much is still transferable from the shop floor.
function lumirise_render_line_transfer(frm) {
	const field = frm.fields_dict.lr_line_transfer_html;
	if (!field) return; // custom field not migrated yet
	const $w = field.$wrapper;
	$w.html(`<div class="text-muted">${__("Loading line-transfer breakdown…")}</div>`);
	frappe.call({
		method: "lumirise_custom.production.line_transfer_breakdown",
		args: { work_order: frm.doc.name },
		callback(r) {
			const d = r.message;
			if (!d || d.not_submitted) {
				$w.html(`<div class="text-muted">${__("Submit the Work Order to see the line-transfer breakdown.")}</div>`);
				return;
			}
			$w.html(lumirise_line_transfer_html(d));
		},
	});
}

function lumirise_line_transfer_html(d) {
	const n = (v) => format_number(flt(v), null, 2);
	const chip = (label, val, color) =>
		`<div style="flex:1;min-width:150px;border:1px solid var(--border-color);border-radius:8px;padding:10px 12px;">
			<div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px;">${label}</div>
			<div style="font-size:20px;font-weight:600;color:${color};">${n(val)}</div>
		</div>`;

	const summary = `
		<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px;">
			${chip(__("WO Required"), d.wo_qty, "var(--text-color)")}
			${chip(__("Transferred to lines"), d.transferred_total, "#1f7a1f")}
			${chip(__("Produced"), d.produced_total, "#1f6fd6")}
			${chip(__("Balance to produce"), d.balance_to_produce, d.balance_to_produce > 0 ? "#d68a1f" : "#1f7a1f")}
			${chip(__("Total on shop floor"), d.shop_floor_total, d.shop_floor_total > 0 ? "#1f6fd6" : "#8d95a0")}
			${chip(__("Transferable now"), d.transferable_now, d.transferable_now > 0 ? "#d68a1f" : "#8d95a0")}
		</div>`;

	let rows;
	if (!d.lines.length) {
		rows = `<tr><td colspan="4" class="text-muted" style="padding:10px;">${__("Nothing transferred to any line yet.")}</td></tr>`;
	} else {
		rows = d.lines
			.map(
				(l) => `<tr>
				<td style="padding:8px 10px;">${frappe.utils.escape_html(l.line)}</td>
				<td style="padding:8px 10px;text-align:right;">${n(l.transferred)}</td>
				<td style="padding:8px 10px;text-align:right;">${n(l.produced)}</td>
				<td style="padding:8px 10px;text-align:right;font-weight:600;">${n(l.wip_on_line)}</td>
			</tr>`
			)
			.join("");
	}

	const table = `
		<table style="width:100%;border-collapse:collapse;border:1px solid var(--border-color);border-radius:8px;overflow:hidden;">
			<thead>
				<tr style="background:var(--control-bg);">
					<th style="padding:8px 10px;text-align:left;">${__("Production Line")}</th>
					<th style="padding:8px 10px;text-align:right;">${__("Transferred")}</th>
					<th style="padding:8px 10px;text-align:right;">${__("Produced")}</th>
					<th style="padding:8px 10px;text-align:right;">${__("Still on line (WIP)")}</th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>
		<div class="text-muted" style="margin-top:8px;font-size:12px;">
			${__("Transferable now = kit currently on the shop floor (what the Material Request delivered). Raise another Material Request to send more.")}
		</div>`;

	return summary + table;
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
