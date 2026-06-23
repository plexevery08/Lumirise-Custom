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

frappe.listview_settings["Indent"] = {
	onload(listview) {
		listview.page.add_action_item(__("Create Purchase Plan (merge)"), () => {
			const names = listview.get_checked_items().map((d) => d.name);
			if (!names.length) {
				frappe.msgprint(__("Select one or more Indents first."));
				return;
			}
			make_plan(names);
		});
	},
	get_indicator(doc) {
		if (doc.workflow_state === "Ordered") return [__("Ordered"), "green", "workflow_state,=,Ordered"];
		if (doc.docstatus === 1) return [__("Approved"), "blue", "docstatus,=,1"];
		return [__("Draft"), "orange", "docstatus,=,0"];
	},
};
