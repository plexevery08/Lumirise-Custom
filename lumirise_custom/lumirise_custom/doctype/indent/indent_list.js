// Indent LIST view settings. Must live in {doctype}_list.js — the form's indent.js
// is not loaded on the list page.
//   - "Pending for PO"  : approved (submitted) indents not yet ordered.
//   - "Create Purchase Plan (merge)" : merge the checked indents into one plan.

frappe.listview_settings["Indent"] = {
	onload(listview) {
		// One-click "Pending for PO" = approved (submitted) indents not yet ordered.
		listview.page.add_inner_button(__("Pending for PO"), () => {
			listview.filter_area.clear().then(() => {
				listview.filter_area.add([
					["Indent", "workflow_state", "=", "Approved"],
				]);
			});
		});

		listview.page.add_action_item(__("Create Purchase Plan (merge)"), () => {
			const names = listview.get_checked_items().map((d) => d.name);
			if (!names.length) {
				frappe.msgprint(__("Select one or more Indents first."));
				return;
			}
			frappe.call({
				method: "lumirise_custom.lumirise_custom.doctype.indent.indent.make_purchase_plan",
				args: { indents: names },
				freeze: true,
				freeze_message: __("Merging indents into a Purchase Plan…"),
				callback(r) {
					if (!r.message) return;
					frappe.show_alert({
						message: __("Purchase Plan {0} created — assign a vendor per line, then split into POs.", [r.message]),
						indicator: "green",
					});
					frappe.set_route("Form", "Purchase Plan", r.message);
				},
			});
		});
	},
	get_indicator(doc) {
		if (doc.workflow_state === "Ordered") return [__("Ordered"), "green", "workflow_state,=,Ordered"];
		if (doc.docstatus === 1) return [__("Approved"), "blue", "docstatus,=,1"];
		return [__("Draft"), "orange", "docstatus,=,0"];
	},
};
