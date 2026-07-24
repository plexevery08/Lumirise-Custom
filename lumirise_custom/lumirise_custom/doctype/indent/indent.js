// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Indent form: build a Purchase Plan from THIS indent.
// Indent list: select MANY approved indents -> ONE Purchase Plan (common parts
// summed). Ajay review 2026-06-14: the plan is where the buyer assigns a VENDOR
// per item and then splits the demand into one Purchase Order per vendor (volume
// discounts). We never go straight to a single supplier PO anymore.

frappe.ui.form.on("Indent", {
	refresh(frm) {
		const is_service = frm.doc.indent_type === "Service";

		if (frm.doc.docstatus === 1 && frm.doc.workflow_state === "Ordered") {
			frm.set_intro(__("This indent has been converted to a Purchase Order."), "green");
		}
		if (is_service && frm.doc.service_order_ref) {
			frm.set_intro(__("Service Order created: {0}", [frm.doc.service_order_ref]), "green");
		}

		if (frm.doc.docstatus === 1 && frm.doc.workflow_state !== "Ordered") {
			if (is_service) {
				// Service indent -> subcontract PO (the native "Service Order"), which then
				// feeds a Subcontracting Order. Purchase indent keeps the Purchase Plan path.
				frm.add_custom_button(__("Create Service Order"), () => make_service_order(frm), __("Create"));
			} else {
				frm.add_custom_button(__("Create Purchase Plan"), () => make_plan([frm.doc.name]), __("Create"));
			}
		}
	},

	// Phase-2 point 38: balance column tracks the SELECTED warehouse only.
	balance_warehouse(frm) {
		(frm.doc.items || []).forEach((row) => set_row_balance(frm, row.doctype, row.name));
	},
});

frappe.ui.form.on("Indent Item", {
	item_code(frm, cdt, cdn) {
		set_row_balance(frm, cdt, cdn);
	},
});

function set_row_balance(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	if (!row.item_code) {
		frappe.model.set_value(cdt, cdn, "stock_at_warehouse", 0);
		return;
	}
	frappe.call({
		method: "lumirise_custom.lumirise_custom.doctype.indent.indent.warehouse_balance",
		args: { item_code: row.item_code, warehouse: frm.doc.balance_warehouse || "Stores - L" },
		callback(r) {
			frappe.model.set_value(cdt, cdn, "stock_at_warehouse", r.message || 0);
		},
	});
}

function make_service_order(frm) {
	frappe.call({
		method: "lumirise_custom.service_order.make_service_order",
		args: { indent: frm.doc.name },
		freeze: true,
		freeze_message: __("Building the subcontract Purchase Order…"),
		callback(r) {
			if (!r.message) return;
			frappe.show_alert({ message: __("Service Order (PO) {0} created — set the vendor rate, then run Create → Subcontracting Order.", [r.message]), indicator: "green" });
			frm.reload_doc();
			frappe.set_route("Form", "Purchase Order", r.message);
		},
	});
}

function make_plan(indents) {
	frappe.call({
		method: "lumirise_custom.lumirise_custom.doctype.indent.indent.make_purchase_plan",
		args: { indents },
		freeze: true,
		freeze_message: __("Merging indents into a Purchase Plan…"),
		callback(r) {
			if (!r.message) return;
			frappe.show_alert({ message: __("Purchase Plan {0} created — assign a vendor per line, then split into POs.", [r.message]), indicator: "green" });
			frappe.set_route("Form", "Purchase Plan", r.message);
		},
	});
}

// NOTE: Indent LIST settings (Pending for PO filter, merge action, indicators)
// live in indent_list.js — the form controller is not loaded on the list page.
