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
		render_supplier_split(frm);
		render_kit_calc(frm);
	},
	// Global Supplier -> cascade onto every line (buyer can then override per item).
	lr_global_supplier(frm) {
		if (!frm.doc.lr_global_supplier) return;
		(frm.doc.items || []).forEach((row) => {
			row.supplier = frm.doc.lr_global_supplier;
		});
		frm.refresh_field("items");
		render_supplier_split(frm);
	},
	// Parent-form events for the child table (add/remove rows).
	items_add(frm, cdt, cdn) {
		// A new line defaults to the global supplier (still overridable).
		if (frm.doc.lr_global_supplier) {
			frappe.model.set_value(cdt, cdn, "supplier", frm.doc.lr_global_supplier);
		}
		draw_balance(frm);
		render_supplier_split(frm);
	},
	items_remove(frm) { draw_balance(frm); render_supplier_split(frm); },
});

// Recompute the balance/kit view when an order qty changes.
frappe.ui.form.on("Purchase Plan Item", {
	qty(frm) { draw_balance(frm); render_supplier_split(frm); draw_kit_calc(frm); },
	// Per-item supplier override -> refresh the supplier-wise split.
	supplier(frm) { render_supplier_split(frm); },
	model(frm) { render_kit_calc(frm); },
	item_code(frm) { draw_kit_calc(frm); },
});

// Kit Calculator (change-list 6.3): per model, how many COMPLETE kits the ordered
// component quantities build (min over components of ordered ÷ per-kit) and what is
// left over LOOSE — recomputed live as the buyer edits quantities, so they can top
// up loose parts into full kits for better vendor pricing.
function render_kit_calc(frm) {
	const field = frm.fields_dict.lr_kit_calc_html;
	if (!field || frm.is_new()) {
		if (field) field.$wrapper.html(`<div class="text-muted">${__("Save the plan to use the Kit Calculator.")}</div>`);
		return;
	}
	if (frm._kit_bom && frm._kit_bom_name === frm.doc.name) { draw_kit_calc(frm); return; }
	frappe.call({
		method: "lumirise_custom.lumirise_custom.doctype.purchase_plan.purchase_plan.get_kit_bom",
		args: { plan_name: frm.doc.name },
		callback(r) {
			frm._kit_bom = r.message || {};
			frm._kit_bom_name = frm.doc.name;
			draw_kit_calc(frm);
		},
	});
}

function draw_kit_calc(frm) {
	const field = frm.fields_dict.lr_kit_calc_html;
	if (!field || frm.is_new()) return;
	const bom = frm._kit_bom || {};
	const esc = (v) => frappe.utils.escape_html(String(v == null ? "" : v));
	const num = (v) => format_number(flt(v), null, 2);

	// Ordered qty per component, summed live from the plan lines.
	const ordered = {};
	(frm.doc.items || []).forEach((row) => {
		if (!row.item_code) return;
		ordered[row.item_code] = flt(ordered[row.item_code]) + flt(row.qty);
	});

	const models = Object.keys(bom).sort();
	if (!models.length) {
		field.$wrapper.html(`<div class="text-muted">${__("No models on this plan (or their FG items have no default BOM), so there are no kits to compute.")}</div>`);
		return;
	}

	let html = `<p class="text-muted small">${__("Per model: complete kits = min(ordered ÷ per-kit) across components; the rest are loose parts. Bump a component's qty above to see kits recalculate.")}</p>`;

	models.forEach((model) => {
		const info = bom[model];
		if (info.no_bom) {
			html += `<div style="margin-bottom:12px;"><b>${esc(model)}</b> — <span class="text-danger">${__("no default BOM set on the FG item")}</span></div>`;
			return;
		}
		const comps = info.components || {};
		const codes = Object.keys(comps);
		// complete kits = floor of the min (ordered ÷ per-kit) across components
		let kits = Infinity;
		codes.forEach((c) => {
			const perKit = flt(comps[c]);
			if (perKit <= 0) return;
			kits = Math.min(kits, Math.floor(flt(ordered[c]) / perKit));
		});
		if (!isFinite(kits)) kits = 0;

		const rows = codes.sort().map((c) => {
			const perKit = flt(comps[c]);
			const ord = flt(ordered[c]);
			const used = kits * perKit;
			const loose = ord - used;
			const nextKit = Math.max(0, (kits + 1) * perKit - ord); // shortfall to 1 more kit
			const bottleneck = perKit > 0 && Math.floor(ord / perKit) === kits;
			return `<tr>
				<td>${esc(c)}${bottleneck ? ` <span class="indicator-pill orange">${__("limits kits")}</span>` : ""}</td>
				<td class="text-right">${num(ord)}</td>
				<td class="text-right">${num(perKit)}</td>
				<td class="text-right">${num(used)}</td>
				<td class="text-right"><b>${num(loose)}</b></td>
				<td class="text-right">${nextKit > 0 ? num(nextKit) : "—"}</td>
			</tr>`;
		}).join("");

		html += `<div style="margin-bottom:16px;">
			<div style="font-weight:600;margin-bottom:4px;">${esc(model)} —
				<span class="indicator-pill green">${num(kits)} ${__("complete kit(s)")}</span></div>
			<table class="table table-bordered" style="font-size:12px;margin-bottom:0;">
				<thead><tr>
					<th>${__("Component")}</th>
					<th class="text-right">${__("Ordered")}</th>
					<th class="text-right">${__("Per Kit")}</th>
					<th class="text-right">${__("Used in kits")}</th>
					<th class="text-right">${__("Loose")}</th>
					<th class="text-right">${__("Add for next kit")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`;
	});

	field.$wrapper.html(html);
}

// One read-only table per supplier: which items (and how much) go to that vendor's
// PO. Mirrors "as much as supplier selected, that many POs" (Fathom 2026-06-29).
function render_supplier_split(frm) {
	const field = frm.fields_dict.lr_supplier_split_html;
	if (!field) return;
	const esc = (v) => frappe.utils.escape_html(String(v == null ? "" : v));
	const num = (v) => format_number(flt(v), null, 2);

	const groups = {};       // supplier -> rows
	const unassigned = [];
	(frm.doc.items || []).forEach((row) => {
		if (!row.item_code) return;
		if (row.supplier) (groups[row.supplier] = groups[row.supplier] || []).push(row);
		else unassigned.push(row);
	});

	const suppliers = Object.keys(groups).sort();
	if (!suppliers.length && !unassigned.length) {
		field.$wrapper.html(`<div class="text-muted">${__("Add items and assign suppliers to see the supplier-wise split.")}</div>`);
		return;
	}

	const tableFor = (title, rows, badge) => {
		let total = 0;
		const body = rows.map((r) => {
			total += flt(r.qty);
			return `<tr>
				<td>${esc(r.item_code)}</td>
				<td>${esc(r.item_name || "")}</td>
				<td class="text-right">${num(r.qty)}</td>
				<td>${esc(r.uom || "")}</td>
				<td>${esc(r.model || "")}</td>
			</tr>`;
		}).join("");
		return `<div style="margin-bottom:14px;">
			<div style="font-weight:600;margin-bottom:4px;">
				<span class="indicator-pill ${badge}">${esc(title)}</span>
				<span class="text-muted" style="font-weight:normal;">— ${rows.length} ${__("item(s)")}, ${__("total qty")} ${num(total)}</span>
			</div>
			<table class="table table-bordered" style="font-size:12px;margin-bottom:0;">
				<thead><tr>
					<th>${__("Item Code")}</th><th>${__("Item Name")}</th>
					<th class="text-right">${__("Qty")}</th><th>${__("UOM")}</th><th>${__("Model / FG")}</th>
				</tr></thead>
				<tbody>${body}</tbody>
			</table>
		</div>`;
	};

	let html = `<p class="text-muted small">${__("One table per supplier — each becomes a separate Purchase Order on 'Create Purchase Orders (split by vendor)'.")}</p>`;
	html += suppliers.map((s) => tableFor(s, groups[s], "blue")).join("");
	if (unassigned.length) {
		html += tableFor(__("⚠ No supplier assigned"), unassigned, "red");
	}
	field.$wrapper.html(html);
}

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
