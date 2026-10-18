function creator_group_number(frm) {
	const groups = new Set(
		(frm.doc.configurations || []).map((row) => row.configuration_group).filter(Boolean)
	);
	return groups.size + 1;
}

function render_creator_help(frm) {
	const field = frm.get_field("creator_help");
	if (!field || !field.$wrapper) return;
	const groups = new Set(
		(frm.doc.configurations || []).map((row) => row.configuration_group).filter(Boolean)
	).size;
	const products = (frm.doc.configurations || []).length;
	field.$wrapper.html(`
		<div class="alert alert-info mb-3">
			<div class="font-weight-bold">${__("Rookie flow")}</div>
			<div>${__("1. Add a product group → 2. Review the queue → 3. Generate & Send for Approval → 4. Approver calculates and approves → 5. ERP Quotation is created.")}</div>
			<div class="mt-2 text-muted">${__("Queued: {0} group(s), {1} product configuration(s). Mono-box finishes and master-box caselots come from the pricing masters automatically.", [groups, products])}</div>
		</div>
	`);
}

function toggle_legacy_fields(frm) {
	const has_queue = (frm.doc.configurations || []).length > 0;
	const show_legacy = Boolean(frm.__show_price_sheet_legacy) || (!frm.is_new() && !has_queue);
	frm.toggle_display("sec_config", show_legacy);
}

async function open_creator_dialog(frm) {
	const response = await frappe.call({
		method: "lumirise_custom.lumirise_custom.doctype.price_sheet.price_sheet.get_creator_options",
	});
	const options = response.message || {};
	const zones = ["", ...(options.transport_zones || [])];
	const credit_days = [
		"",
		...(options.credit_terms || []).map((row) => String(row.credit_days)),
	];
	const credit_description = (options.credit_terms || [])
		.map((row) => `${row.credit_days} ${__("days")} (+${row.percentage}%)`)
		.join(" · ");

	const dialog = new frappe.ui.Dialog({
		title: __("Quotation Creator — Add Product Group"),
		size: "extra-large",
		fields: [
			{
				fieldname: "customer",
				fieldtype: "Link",
				label: __("Customer"),
				options: "Customer",
				default: frm.doc.customer,
				reqd: 1,
			},
			{ fieldtype: "Section Break", label: __("Products") },
			{
				fieldname: "item_group",
				fieldtype: "Link",
				label: __("Category"),
				options: "Item Group",
				description: __("Optional. Choose a category first to shorten the product list."),
			},
			{
				fieldname: "products",
				fieldtype: "Table",
				label: __("Products"),
				in_place_edit: true,
				reqd: 1,
				fields: [
					{
						fieldname: "item",
						fieldtype: "Link",
						label: __("Product"),
						options: "Item",
						in_list_view: 1,
						reqd: 1,
					},
				],
			},
			{ fieldtype: "Section Break", label: __("Packaging") },
			{
				fieldname: "master_box_finish",
				fieldtype: "Link",
				label: __("Master Box Finish"),
				options: "Box Finish",
				description: __("Leave blank for No Master Box. Available caselots are added automatically."),
				get_query() {
					return { query: "lumirise_custom.queries.master_box_finish_query" };
				},
			},
			{
				fieldname: "mono_box_note",
				fieldtype: "HTML",
				options: `<p class="text-muted small">${__("All mono-box finishes that have a price for each product will be included, matching the original sales app.")}</p>`,
			},
			{ fieldtype: "Section Break", label: __("Delivery") },
			{
				fieldname: "delivery_type",
				fieldtype: "Select",
				label: __("Delivery Type"),
				options: "Ex-Factory\nTransport",
				default: "Ex-Factory",
				reqd: 1,
				change() {
					const transport = dialog.get_value("delivery_type") === "Transport";
					dialog.set_df_property("transport_type", "hidden", !transport);
					dialog.set_df_property("transport_zone", "hidden", !transport);
					dialog.set_df_property("transport_type", "reqd", transport);
					dialog.set_df_property("transport_zone", "reqd", transport);
					if (!transport) dialog.set_values({ transport_type: "", transport_zone: "" });
				},
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "transport_type",
				fieldtype: "Select",
				label: __("Transport Type"),
				options: "\nPublic\nPrivate",
				default: "Private",
				hidden: 1,
			},
			{
				fieldname: "transport_zone",
				fieldtype: "Select",
				label: __("Transport Zone"),
				options: zones,
				hidden: 1,
			},
			{ fieldtype: "Section Break", label: __("Payment") },
			{
				fieldname: "payment_type",
				fieldtype: "Select",
				label: __("Payment Type"),
				options: "Advance\nCredit",
				default: "Advance",
				reqd: 1,
				change() {
					const credit = dialog.get_value("payment_type") === "Credit";
					dialog.set_df_property("credit_days", "hidden", !credit);
					dialog.set_df_property("credit_days", "reqd", credit);
					if (!credit) dialog.set_value("credit_days", "");
				},
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "credit_days",
				fieldtype: "Select",
				label: __("Credit Days"),
				options: credit_days,
				description: credit_description,
				hidden: 1,
			},
		],
		primary_action_label: __("Add to Queue"),
		async primary_action(values) {
			const products = [...new Set((values.products || []).map((row) => row.item).filter(Boolean))];
			if (!products.length) frappe.throw(__("Add at least one product"));
			if ((frm.doc.configurations || []).length && frm.doc.customer !== values.customer) {
				frappe.throw(__("The queue belongs to {0}. Clear it before changing customer.", [frm.doc.customer]));
			}

			await frm.set_value("customer", values.customer);
			const group = __("Group {0}", [creator_group_number(frm)]);
			products.forEach((item) => {
				frm.add_child("configurations", {
					configuration_group: group,
					item,
					mono_box_mode: "All Priced Finishes",
					master_box_finish: values.master_box_finish || null,
					delivery_type: values.delivery_type,
					transport_type: values.delivery_type === "Transport" ? values.transport_type : null,
					transport_zone: values.delivery_type === "Transport" ? values.transport_zone : null,
					payment_type: values.payment_type,
					credit_days: values.payment_type === "Credit" ? cint(values.credit_days) : 0,
				});
			});
			frm.refresh_field("configurations");
			frm.dirty();
			dialog.hide();
			render_creator_help(frm);
			toggle_legacy_fields(frm);
			frappe.show_alert({
				message: __("{0} product(s) added to {1}", [products.length, group]),
				indicator: "green",
			});
		},
	});
	const product_grid = dialog.get_field("products").grid;
	product_grid.get_field("item").get_query = () => ({
		query: "lumirise_custom.queries.quotable_item_query",
		filters: { item_group: dialog.get_value("item_group") || "" },
	});
	dialog.show();
}

async function generate_and_submit(frm) {
	if (!(frm.doc.configurations || []).length && !(frm.doc.products || []).length) {
		frappe.throw(__("Add at least one product group first"));
	}
	await frm.save();
	await frm.savesubmit();
	frappe.show_alert({
		message: __("Price Sheet generated and sent for approval"),
		indicator: "green",
	});
}

frappe.ui.form.on("Price Sheet", {
	setup(frm) {
		frm.set_query("master_box_finish", () => ({
			query: "lumirise_custom.queries.master_box_finish_query",
		}));
		frm.set_query("mono_box_finishes", () => ({
			query: "lumirise_custom.queries.mono_box_finish_query",
			filters: { items: (frm.doc.products || []).map((row) => row.item) },
		}));
		frm.set_query("credit_term", () => ({ filters: { payment_type: "Credit" } }));
		frm.set_query("item", "configurations", () => ({
			query: "lumirise_custom.queries.quotable_item_query",
		}));
		frm.set_query("master_box_finish", "configurations", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				query: "lumirise_custom.queries.master_box_finish_query",
				filters: { item: row.item || "" },
			};
		});
		frm.set_query("mono_box_finish", "approval_items", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				query: "lumirise_custom.queries.mono_box_finish_query",
				filters: { items: row.item ? [row.item] : [] },
			};
		});
		frm.set_query("master_box_finish", "approval_items", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				query: "lumirise_custom.queries.master_box_finish_query",
				filters: { item: row.item || "" },
			};
		});
	},

	onload(frm) {
		if (frm.is_new() && !frm.__quotation_creator_opened) {
			frm.__quotation_creator_opened = true;
			setTimeout(() => open_creator_dialog(frm), 250);
		}
	},

	refresh(frm) {
		render_creator_help(frm);
		toggle_legacy_fields(frm);

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Add Product Group"), () => open_creator_dialog(frm)).addClass("btn-primary");
			if ((frm.doc.configurations || []).length || (frm.doc.products || []).length) {
				frm.add_custom_button(__("Generate & Send for Approval"), () => {
					frappe.confirm(
						__("Generate the customer price sheet and send it for approval?"),
						() => generate_and_submit(frm)
					);
				}).addClass("btn-success");
			}
			frm.add_custom_button(__("Use Legacy Form"), () => {
				frm.__show_price_sheet_legacy = true;
				toggle_legacy_fields(frm);
			}, __("Advanced"));
		}

		const is_approver =
			frappe.user.has_role("Sales Approver") || frappe.user.has_role("System Manager");
		if (frm.doc.docstatus === 1 && frm.doc.status === "Pending Approval" && is_approver) {
			if (!(frm.doc.approval_items || []).length) {
				frm.add_custom_button(__("1. Prepare Approval Lines"), async () => {
					await frm.call("populate_approval_items");
					await frm.reload_doc();
				});
			}
			if ((frm.doc.approval_items || []).length) {
				frm.add_custom_button(__("2. Calculate Prices"), async () => {
					await frm.call("preview_prices");
					await frm.reload_doc();
					frappe.show_alert({
						message: __("Prices calculated. Review the customer prices and variances."),
						indicator: "blue",
					});
				});
			}
			frm.add_custom_button(__("3. Approve & Create Quotation"), () => {
				frappe.confirm(__("Approve and create the ERP Quotation?"), async () => {
					const result = await frm.call("approve");
					frappe.show_alert({
						message: __("Approved — Quotation {0} created", [result.message]),
						indicator: "green",
					});
					await frm.reload_doc();
				});
			}).addClass("btn-success");
			frm.add_custom_button(__("Reject"), () => {
				frappe.prompt(
					{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks"), reqd: 1 },
					async (values) => {
						await frm.call("reject", { remarks: values.remarks });
						await frm.reload_doc();
					},
					__("Reject Price Sheet")
				);
			}).addClass("btn-danger");
		}

		if (frm.doc.quotation) {
			frm.add_custom_button(__("Open Quotation"), async () => {
				if (await frappe.db.exists("Quotation", frm.doc.quotation)) {
					frappe.set_route("Form", "Quotation", frm.doc.quotation);
				} else {
					frappe.msgprint({
						title: __("Broken Quotation Link"),
						message: __("Quotation {0} no longer exists. Ask a System Manager to repair this Price Sheet.", [frm.doc.quotation]),
						indicator: "red",
					});
				}
			});
		}

		if (frm.doc.status === "Pending Approval") {
			const days_left = frappe.datetime.get_diff(frm.doc.valid_till, frappe.datetime.get_today());
			frm.set_intro(
				days_left >= 0
					? __("Approval window: {0} day(s) left", [days_left])
					: __("Approval window has expired"),
				days_left >= 0 ? "orange" : "red"
			);
		}
	},

	payment_type(frm) {
		if (frm.doc.payment_type !== "Credit") {
			frm.set_value({ credit_term: null, credit_days: 0, credit_percentage: 0 });
		}
	},

	delivery_type(frm) {
		if (frm.doc.delivery_type !== "Transport") {
			frm.set_value({ transport_type: null, transport_zone: null });
		}
	},
});

frappe.ui.form.on("Price Sheet Approval Item", {
	is_sample_or_exception(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.is_sample_or_exception) {
			frappe.model.set_value(cdt, cdn, "exception_reason", "");
		}
	},

	async master_box_finish(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.master_box_finish) {
			frappe.model.set_value(cdt, cdn, "master_box_caselot", null);
			return;
		}
		const response = await frappe.call({
			method: "lumirise_custom.lumirise_custom.doctype.price_sheet.price_sheet.get_master_box_caselot_options",
			args: { item: row.item, finish: row.master_box_finish },
		});
		const caselots = response.message || [];
		if (!caselots.length) {
			frappe.model.set_value(cdt, cdn, "master_box_caselot", null);
			frappe.msgprint({
				title: __("Missing Master Box Pricing"),
				message: __("No priced caselot exists for {0} / {1}.", [row.item, row.master_box_finish]),
				indicator: "red",
			});
			return;
		}
		if (caselots.length === 1) {
			frappe.model.set_value(cdt, cdn, "master_box_caselot", caselots[0]);
			return;
		}
		frappe.prompt(
			{
				fieldname: "caselot",
				fieldtype: "Select",
				label: __("Caselot"),
				options: caselots.map(String),
				reqd: 1,
			},
			(values) => frappe.model.set_value(cdt, cdn, "master_box_caselot", cint(values.caselot)),
			__("Choose Master Box Caselot")
		);
	},

	transport_mode(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.transport_mode === "No Transport") {
			frappe.model.set_value(cdt, cdn, "transport_type", "");
			frappe.model.set_value(cdt, cdn, "transport_zone", "");
		}
	},
});
