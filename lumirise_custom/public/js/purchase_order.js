// Lumirise Purchase Order: (1) start the inbound quality chain, and
// (2) the BOM Reconciliation tab — full-kit tally + per-model price split.
frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Vendor PDI"), () => {
				frappe.model.open_mapped_doc({
					method: "lumirise_custom.chain.make_vendor_pdi",
					frm: frm,
				});
			}, __("Create"));
		}
		render_bom_reco(frm);
	},
	lr_indent_refs(frm) {
		render_bom_reco(frm);
	},
});

function render_bom_reco(frm) {
	const field = frm.fields_dict.lr_bom_reco_html;
	if (!field) return;
	const $w = field.$wrapper;
	if (frm.is_new()) {
		$w.html(`<div class="text-muted">${__("Save the Purchase Order to see the BOM reconciliation.")}</div>`);
		return;
	}
	$w.html(`<div class="text-muted">${__("Loading BOM reconciliation…")}</div>`);
	frappe.call({
		method: "lumirise_custom.purchase_reco.get_bom_reconciliation",
		args: { po_name: frm.doc.name },
		callback(r) {
			const data = r.message || {};
			frm._bom_reco_data = data;
			$w.html(build_reco_html(data));
			$w.find("[data-reco-recompute]").on("click", () => render_bom_reco(frm));
			$w.find("[data-reco-export]").on("click", () => export_reco(frm));
		},
	});
}

function esc(v) { return frappe.utils.escape_html(String(v == null ? "" : v)); }
function num(v) { return format_number(flt(v), null, 2); }

function build_reco_html(data) {
	const toolbar = `
		<div style="margin-bottom:12px;display:flex;gap:8px;">
			<button class="btn btn-default btn-sm" data-reco-recompute>${__("Recompute")}</button>
			<button class="btn btn-default btn-sm" data-reco-export>${__("Export")}</button>
		</div>`;

	if (!data.has_refs) {
		return toolbar + `<div class="text-muted">${__("This PO has no linked Indents (Indent References empty), so there is no kit to reconcile.")}</div>`;
	}
	if (!data.kit || !data.kit.length) {
		return toolbar + `<div class="text-muted">${__("No models found on the linked Indents.")}</div>`;
	}

	let html = toolbar;

	// ---- Kit reconciliation per model
	html += `<h5>${__("Kit Reconciliation")}</h5>
		<p class="text-muted small">${__("Full BOM kit for each model. Red = component missing from the indents; amber = short of the required qty.")}</p>`;
	data.kit.forEach((m) => {
		html += `<div style="margin:10px 0 4px;"><b>${esc(m.model)}</b>
			<span class="text-muted">(${__("FG qty")}: ${num(m.fg_qty)})</span></div>`;
		html += `<table class="table table-bordered" style="font-size:12px;margin-bottom:6px;">
			<thead><tr>
				<th>${__("Component")}</th>
				<th class="text-right">${__("Required")}</th>
				<th class="text-right">${__("In Indent")}</th>
				<th class="text-right">${__("In Stock")}</th>
				<th>${__("Status")}</th>
			</tr></thead><tbody>`;
		(m.components || []).forEach((c) => {
			let bg = "", status = __("OK"), badge = "green";
			if (c.missing) { bg = "background:#fde2e2;"; status = __("MISSING"); badge = "red"; }
			else if (flt(c.in_indent) < flt(c.required)) { bg = "background:#fff3cd;"; status = __("Short"); badge = "orange"; }
			html += `<tr style="${bg}">
				<td><b>${esc(c.component)}</b> <span class="text-muted">${esc(c.item_name)}</span></td>
				<td class="text-right">${num(c.required)}</td>
				<td class="text-right">${num(c.in_indent)}</td>
				<td class="text-right">${num(c.in_stock)}</td>
				<td><span class="indicator-pill ${badge}">${status}</span></td>
			</tr>`;
		});
		html += `</tbody></table>`;
	});

	// ---- Per-model price split
	html += `<h5 style="margin-top:20px;">${__("Per-Model Price Split")}</h5>
		<p class="text-muted small">${__("How each PO line's quantity and cost splits across the models that use it. Rate fetched from the RM Price Book.")}</p>`;
	(data.split || []).forEach((s) => {
		html += `<div style="margin:10px 0 4px;"><b>${esc(s.item_code)}</b>
			<span class="text-muted">${esc(s.item_name)}</span> — ${__("PO Qty")}: ${num(s.total_qty)}
			@ ₹${num(s.rate)} = <b>₹${num(s.total_amount)}</b></div>`;
		html += `<table class="table table-bordered" style="font-size:12px;margin-bottom:6px;">
			<thead><tr>
				<th>${__("Model")}</th>
				<th class="text-right">${__("Qty")}</th>
				<th class="text-right">${__("Rate")}</th>
				<th class="text-right">${__("Amount")}</th>
			</tr></thead><tbody>`;
		(s.rows || []).forEach((row) => {
			html += `<tr>
				<td>${esc(row.model)}</td>
				<td class="text-right">${num(row.qty)}</td>
				<td class="text-right">₹${num(row.rate)}</td>
				<td class="text-right">₹${num(row.amount)}</td>
			</tr>`;
		});
		html += `</tbody></table>`;
	});

	return html;
}

function export_reco(frm) {
	const data = frm._bom_reco_data;
	if (!data || !data.kit) { frappe.msgprint(__("Nothing to export yet.")); return; }
	const rows = [["Section", "Model", "Component", "Item Name", "Required/Qty", "In Indent", "In Stock", "Rate", "Amount", "Status"]];
	(data.kit || []).forEach((m) => {
		(m.components || []).forEach((c) => {
			rows.push(["Kit", m.model, c.component, c.item_name, flt(c.required), flt(c.in_indent), flt(c.in_stock), "", "",
				c.missing ? "MISSING" : (flt(c.in_indent) < flt(c.required) ? "Short" : "OK")]);
		});
	});
	(data.split || []).forEach((s) => {
		(s.rows || []).forEach((row) => {
			rows.push(["Price Split", row.model, s.item_code, s.item_name, flt(row.qty), "", "", flt(row.rate), flt(row.amount), ""]);
		});
	});
	const csv = rows.map((r) => r.map((v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`).join(",")).join("\n");
	const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = `BOM_Reconciliation_${frm.doc.name}.csv`;
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
}
