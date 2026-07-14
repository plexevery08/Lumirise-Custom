frappe.ui.form.on("Lumirise Production Schedule", {
	setup(frm) {
		// Line = a Warehouse, restricted to the configured production lines.
		frm.set_query("production_line", "schedule_lines", () => ({
			query: "lumirise_custom.queries.line_warehouse_query",
		}));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 2) return;

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Sales Orders"), () => {
				frappe.prompt(
					[
						{ fieldname: "from_date", label: __("Delivery From"), fieldtype: "Date" },
						{ fieldname: "to_date", label: __("Delivery To"), fieldtype: "Date" },
						{ fieldname: "customer", label: __("Customer (Brand)"), fieldtype: "Link", options: "Customer" },
						{ fieldname: "only_pending", label: __("Only pending-to-deliver qty"), fieldtype: "Check", default: 1 },
					],
					(v) => {
						const run = () =>
							frappe.call({
								method: "lumirise_custom.lumirise_custom.doctype.lumirise_production_schedule.lumirise_production_schedule.fetch_sales_orders",
								args: {
									schedule_name: frm.doc.name,
									from_date: v.from_date || null,
									to_date: v.to_date || null,
									customer: v.customer || null,
									only_pending: v.only_pending ? 1 : 0,
								},
								freeze: true,
								freeze_message: __("Fetching open Sales Orders…"),
							}).then((r) => {
								frm.reload_doc();
								const m = r.message || {};
								frappe.show_alert({
									message: __("Added {0} FG line(s) from {1} Sales Order(s).", [m.added || 0, m.sales_orders || 0]),
									indicator: (m.added ? "green" : "orange"),
								});
							});
						// The server method loads the saved doc, so persist first when new/dirty.
						if (frm.is_new() || frm.is_dirty()) {
							frm.save().then(run);
						} else {
							run();
						}
					},
					__("Fetch open Sales Orders into the schedule"),
					__("Fetch")
				);
			}).addClass("btn-primary");
		}

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
