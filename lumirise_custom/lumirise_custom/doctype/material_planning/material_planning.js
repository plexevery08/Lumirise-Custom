// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Material Planning cockpit: "Get Sales Orders" loads approved SOs, explodes the
// BOM and fills the reservation/blocking grid. Saving + Submitting = "Post",
// which creates the Production Orders + the consolidated Indent.

frappe.ui.form.on("Material Planning", {
	refresh(frm) {
		// Only while the plan is still with the maker (Draft). Once it is "Submit for
		// Approval"-ed (Pending Planning Manager) it must not be re-pulled/edited.
		const is_draft = frm.doc.docstatus === 0 && (!frm.doc.workflow_state || frm.doc.workflow_state === "Draft");
		if (is_draft) {
			frm.add_custom_button(__("Get Sales Orders"), () => get_sales_orders(frm));
			frm.set_intro(
				__("Click <b>Get Sales Orders</b> to load approved orders and review the blocking columns. Then <b>Submit for Approval</b>; the <b>Planning Manager</b> approves to Post (creates the Production Orders + Indent)."),
				"blue"
			);
		}
		if (frm.doc.docstatus === 1) {
			if (frm.doc.created_indent) {
				frm.add_custom_button(__("Indent"), () => frappe.set_route("Form", "Indent", frm.doc.created_indent), __("View"));
			}
			(frm.doc.created_work_orders || "").split(", ").filter(Boolean).forEach((wo) => {
				frm.add_custom_button(wo, () => frappe.set_route("Form", "Work Order", wo), __("Production Orders"));
			});
		}
	},

	// In-form "Get Sales Orders" button (sits in the FG / Sales Order Plan section,
	// with the fields) — same behaviour as the top toolbar button.
	get_sales_orders_btn(frm) {
		get_sales_orders(frm);
	},
});

function get_sales_orders(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Select Approved Sales Orders"),
		fields: [
			{
				fieldname: "sales_orders",
				fieldtype: "MultiSelectList",
				label: __("Sales Orders"),
				get_data: (txt) =>
					frappe.db.get_link_options("Sales Order", txt, {
						docstatus: 1,
						workflow_state: "Sales Approved",
					}),
			},
		],
		primary_action_label: __("Load"),
		primary_action(values) {
			d.hide();
			if (!values.sales_orders || !values.sales_orders.length) {
				frappe.msgprint(__("Select at least one Sales Order."));
				return;
			}
			frappe.call({
				method: "lumirise_custom.lumirise_custom.doctype.material_planning.material_planning.compute_plan",
				args: { sales_orders: values.sales_orders },
				freeze: true,
				freeze_message: __("Exploding BOMs and computing the plan..."),
				callback(r) {
					if (!r.message) return;
					frm.clear_table("fg_plan");
					frm.clear_table("components");
					(r.message.fg_plan || []).forEach((row) => frm.add_child("fg_plan", row));
					(r.message.components || []).forEach((row) => frm.add_child("components", row));
					frm.refresh_field("fg_plan");
					frm.refresh_field("components");
					frm.dirty();
					frappe.show_alert({ message: __("Plan loaded — review and Submit to Post."), indicator: "green" });
				},
			});
		},
	});
	d.show();
}

// --- Availability colour cues (Phase-2 pt 32) --------------------------------
// Green = enough free stock for the row, amber = partial, red = nothing free.
// Uses available_after_blocking (the number Purchase actually acts on).
function lumirise_colour_components(frm) {
	const grid = frm.fields_dict.components && frm.fields_dict.components.grid;
	if (!grid) return;
	(grid.grid_rows || []).forEach((gr) => {
		const d = gr.doc || {};
		const avail = flt(d.available_after_blocking);
		const req = flt(d.required_qty);
		const colour = req && avail >= req ? "#c6efce" : avail > 0 ? "#ffeb9c" : "#ffc7ce";
		const cell = gr.row && gr.row.find('[data-fieldname="available_after_blocking"]');
		if (cell && cell.length) cell.css("background-color", colour);
	});
}

frappe.ui.form.on("Material Planning", {
	refresh: lumirise_colour_components,
	onload_post_render: lumirise_colour_components,
});

