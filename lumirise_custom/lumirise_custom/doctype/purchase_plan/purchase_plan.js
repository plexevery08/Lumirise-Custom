// Purchase Plan -- merge indents → assign a vendor per line → split into one PO
// per vendor (Ajay review 2026-06-14).
// Plus: a live "Indent vs Order Balance" table (Indent Qty − Going-to-Order Qty
// = Indent Balance, per item) rendered right after the items table.
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

		render_balance(frm);
	},
	// Parent-form events for the child table (add/remove rows).
	items_add(frm) { draw_balance(frm); },
	items_remove(frm) { draw_balance(frm); },
});

// Recompute the balance when an order qty changes.
frappe.ui.form.on("Purchase Plan Item", {
	qty(frm) { draw_balance(frm); },
});

function render_balance(frm) {
	const field = frm.fields_dict.lr_indent_balance_html;
	if (!field) return;
	if (frm.is_new()) {
		field.$wrapper.html(`<div class="text-muted">${__("Save the plan to see the Indent vs Order balance.")}</div>`);
		return;
	}
	// Cache the indent map PER DOCUMENT — Frappe reuses the same frm across docs
	// of a doctype, so a plain frm._indent_qty would leak stale data between plans.
	if (frm._indent_qty && frm._indent_qty_name === frm.doc.name) { draw_balance(frm); return; }
	frappe.call({
		method: "lumirise_custom.lumirise_custom.doctype.purchase_plan.purchase_plan.get_indent_qty",
		args: { plan_name: frm.doc.name },
		callback(r) {
			frm._indent_qty = r.message || {};
			frm._indent_qty_name = frm.doc.name;
			draw_balance(frm);
		},
	});
}

function draw_balance(frm) {
	const field = frm.fields_dict.lr_indent_balance_html;
	if (!field || frm.is_new()) return;
	const indent_qty = frm._indent_qty || {};

	// Going-to-order qty per item, summed live from the plan lines.
	const order_qty = {};
	(frm.doc.items || []).forEach((row) => {
		if (!row.item_code) return;
		order_qty[row.item_code] = flt(order_qty[row.item_code]) + flt(row.qty);
	});

	const codes = Array.from(new Set([...Object.keys(indent_qty), ...Object.keys(order_qty)])).sort();
	if (!codes.length) {
		field.$wrapper.html(`<div class="text-muted">${__("No items to reconcile yet.")}</div>`);
		return;
	}
	if (!Object.keys(indent_qty).length) {
		field.$wrapper.html(`<div class="text-muted">${__("This plan has no linked indents (it wasn't created by merging indents), so there is no indent qty to reconcile.")}</div>`);
		return;
	}

	const esc = (v) => frappe.utils.escape_html(String(v == null ? "" : v));
	const num = (v) => format_number(flt(v), null, 2);

	let html = `<p class="text-muted small">${__("Indent Qty (from the selected indents) − Going-to-Order Qty = Indent Balance still to purchase.")}</p>`;
	html += `<table class="table table-bordered" style="font-size:12px;">
		<thead><tr>
			<th>${__("Item")}</th>
			<th class="text-right">${__("Indent Qty")}</th>
			<th class="text-right">${__("Going to Order")}</th>
			<th class="text-right">${__("Indent Balance")}</th>
			<th>${__("Status")}</th>
		</tr></thead><tbody>`;

	let t_ind = 0, t_ord = 0, t_bal = 0;
	codes.forEach((code) => {
		const iq = flt(indent_qty[code]);
		const oq = flt(order_qty[code]);
		const bal = iq - oq;
		t_ind += iq; t_ord += oq; t_bal += bal;
		// green = fully ordered; amber = balance still to purchase; red = ordering MORE than indented.
		let color, status, badge;
		if (bal > 0.0001) { color = "#fff3cd"; status = __("Balance pending"); badge = "orange"; }
		else if (bal < -0.0001) { color = "#fde2e2"; status = __("Over-ordered"); badge = "red"; }
		else { color = "#e6f4ea"; status = __("Fully ordered"); badge = "green"; }
		const td = `style="background:${color};"`;
		html += `<tr>
			<td ${td}>${esc(code)}</td>
			<td class="text-right" ${td}>${num(iq)}</td>
			<td class="text-right" ${td}>${num(oq)}</td>
			<td class="text-right" ${td}><b>${num(bal)}</b></td>
			<td ${td}><span class="indicator-pill ${badge}">${status}</span></td>
		</tr>`;
	});

	html += `</tbody><tfoot><tr style="font-weight:bold;">
		<td style="background:#f5f5f5;">${__("Total")}</td>
		<td class="text-right" style="background:#f5f5f5;">${num(t_ind)}</td>
		<td class="text-right" style="background:#f5f5f5;">${num(t_ord)}</td>
		<td class="text-right" style="background:#f5f5f5;">${num(t_bal)}</td>
		<td style="background:#f5f5f5;"></td>
	</tr></tfoot></table>`;

	field.$wrapper.html(html);
}
