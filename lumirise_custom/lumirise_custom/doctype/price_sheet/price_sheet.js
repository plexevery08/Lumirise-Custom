frappe.ui.form.on("Price Sheet", {
	setup(frm) {
		// Master box finishes limited to those with Master Box Pricing records.
		
	},

	refresh(frm) {
		// Field-query filters, wrapped so a control-query quirk can never abort
		// refresh() before the approval buttons below are added. (India Compliance's
		// Form subclass + the child-table set_query form on a Table MultiSelect used
		// to throw here, silently hiding the Approve / Prepare / Reject buttons.)
		try {
			frm.set_query("master_box_finish", () => ({
				query: "lumirise_custom.queries.master_box_finish_query",
			}));
			// Mono box finish picker limited to finishes priced for the selected items.
			// NOTE: mono_box_finishes is a Table MultiSelect (no .grid), so the query
			// must be set on the field itself (2-arg form) — the child-table 3-arg form
			// `set_query("box_finish", "mono_box_finishes", ...)` crashes on `.grid`.
			frm.set_query("mono_box_finishes", () => ({
				query: "lumirise_custom.queries.mono_box_finish_query",
				filters: {
					items: (frm.doc.products || []).map((p) => p.item),
				},
			}));
			// Credit term picker: credit terms only.
			frm.set_query("credit_term", () => ({
				filters: { payment_type: "Credit" },
			}));
		} catch (e) {
			// eslint-disable-next-line no-console
			console.warn("Price Sheet: skipping field-query setup —", e);
		}
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.set_intro(
				__("Rows regenerate from the configuration on every save."),
				"blue"
			);
		}

		const is_approver =
			frappe.user.has_role("Sales Approver") || frappe.user.has_role("System Manager");
		if (frm.doc.docstatus === 1 && frm.doc.status === "Pending Approval" && is_approver) {
			if (!(frm.doc.approval_items || []).length) {
				frm.add_custom_button(__("Prepare Approval Lines"), async () => {
					await frm.call("populate_approval_items");
					frm.reload_doc();
				});
			}
			// Calculate (preview) the system price for every line WITHOUT approving —
			// fills base/calculated/variance and seeds a blank customer price with the
			// calculated price. Enter the agreed qty (>= min) on each line first.
			if ((frm.doc.approval_items || []).length) {
				frm.add_custom_button(__("Calculate Prices"), async () => {
					await frm.call("preview_prices");
					frm.reload_doc();
					frappe.show_alert({
						message: __("Prices calculated — review base/calculated/customer price on each line."),
						indicator: "blue",
					});
				});
			}
			frm.add_custom_button(
				__("Approve"),
				() => {
					frappe.confirm(
						__("Approve this price sheet and create a Quotation?"),
						async () => {
							const r = await frm.call("approve");
							frappe.show_alert({
								message: __("Approved — Quotation {0} created", [r.message]),
								indicator: "green",
							});
							frm.reload_doc();
						}
					);
				},
				null
			).addClass("btn-success");
			frm.add_custom_button(__("Reject"), () => {
				frappe.prompt(
					{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
					async (values) => {
						await frm.call("reject", { remarks: values.remarks });
						frm.reload_doc();
					},
					__("Reject Price Sheet")
				);
			}).addClass("btn-danger");
		}
		if (frm.doc.quotation) {
			frm.add_custom_button(__("Open Quotation"), () =>
				frappe.set_route("Form", "Quotation", frm.doc.quotation)
			);
		}
		if (frm.doc.status === "Pending Approval") {
			const days_left = frappe.datetime.get_diff(
				frm.doc.valid_till,
				frappe.datetime.get_today()
			);
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
