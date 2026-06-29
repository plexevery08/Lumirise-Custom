// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Indent form: build a Purchase Plan from THIS indent.
// Indent list: select MANY approved indents -> ONE Purchase Plan (common parts
// summed). Ajay review 2026-06-14: the plan is where the buyer assigns a VENDOR
// per item and then splits the demand into one Purchase Order per vendor (volume
// discounts). We never go straight to a single supplier PO anymore.

frappe.ui.form.on("Indent", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.workflow_state === "Ordered") {
			frm.set_intro(__("This indent has been converted to a Purchase Order."), "green");
		}
		if (frm.doc.docstatus === 1 && frm.doc.workflow_state !== "Ordered") {
			frm.add_custom_button(__("Create Purchase Plan"), () => make_plan([frm.doc.name]), __("Create"));
		}
	},
});

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
