frappe.ui.form.on("Lumirise Production Schedule", {
	refresh(frm) {
		if (frm.doc.docstatus === 2) return;

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Release Day → Job Cards"), () => {
				frappe.prompt(
					{ fieldname: "d", label: __("Production Date"), fieldtype: "Date", reqd: 1 },
					(v) => {
						frappe.call({
							method: "lumirise_custom.lumirise_custom.doctype.lumirise_production_schedule.lumirise_production_schedule.release_day",
							args: { schedule_name: frm.doc.name, production_date: v.d },
							callback: () => frm.reload_doc(),
						});
					},
					__("Release a day's plan"),
					__("Release")
				);
			}, __("Actions"));

			frm.add_custom_button(__("Roll Backlog"), () => {
				frappe.prompt(
					[
						{ fieldname: "f", label: __("From (missed) Date"), fieldtype: "Date", reqd: 1 },
						{ fieldname: "t", label: __("To (backlog) Date"), fieldtype: "Date", reqd: 1 },
					],
					(v) => {
						frappe.call({
							method: "lumirise_custom.lumirise_custom.doctype.lumirise_production_schedule.lumirise_production_schedule.roll_backlog",
							args: { schedule_name: frm.doc.name, from_date: v.f, to_date: v.t },
						});
					},
					__("Roll yesterday's shortfall forward"),
					__("Roll")
				);
			}, __("Actions"));
		}

		frm.add_custom_button(__("Suggested Order"), () => {
			const sos = [...new Set((frm.doc.schedule_lines || [])
				.map(r => r.sales_order).filter(Boolean))];
			if (!sos.length) {
				frappe.msgprint(__("Add schedule lines with Sales Orders first."));
				return;
			}
			frappe.call({
				method: "lumirise_custom.lumirise_custom.doctype.lumirise_production_schedule.lumirise_production_schedule.get_suggested_order",
				args: { sales_orders: sos },
				callback(r) {
					const rows = (r.message || []).map((x, i) =>
						`<tr><td>${i + 1}</td><td>${x.sales_order}</td><td>${x.fg_item}</td>`
						+ `<td>${x.qty}</td><td>${x.urgent ? "URGENT" : "normal"}</td>`
						+ `<td>${x.priority}</td></tr>`).join("");
					frappe.msgprint({
						title: __("Suggested Order (urgent by priority, then normal)"),
						message: `<table class="table table-bordered"><thead><tr>`
							+ `<th>#</th><th>SO</th><th>FG</th><th>Qty</th><th>Type</th><th>Priority</th>`
							+ `</tr></thead><tbody>${rows}</tbody></table>`,
						wide: true,
					});
				},
			});
		});
	},
});
