// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Indent form: pull THIS indent's items into a new Purchase Order.
// Indent list: select MANY approved indents -> ONE consolidated Purchase Order
// (common parts summed). We never pre-set a supplier -- the buyer fills supplier
// and rates on the fresh PO screen we route them to.

frappe.ui.form.on("Indent", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.workflow_state === "Ordered") {
			frm.set_intro(__("This indent has been converted to a Purchase Order."), "green");
		}
		if (frm.doc.docstatus === 1 && frm.doc.workflow_state !== "Ordered") {
			frm.add_custom_button(__("Create Purchase Order"), () => make_po([frm.doc.name]), __("Create"));
		}
	},
});

function make_po(indents) {
	frappe.call({
		method: "lumirise_custom.lumirise_custom.doctype.indent.indent.get_consolidated_po_items",
		args: { indents },
		freeze: true,
		freeze_message: __("Fetching indent items into a new Purchase Order..."),
		callback(r) {
			if (!r.message) return;
			const data = r.message;
			if (!(data.items || []).length) {
				frappe.msgprint(__("No items to order from the selected indent(s)."));
				return;
			}
			// Open a FRESH, unsaved Purchase Order pre-filled with the consolidated
			// items only -- no supplier, no rates. The buyer completes it on screen.
			frappe.model.with_doctype("Purchase Order", () => {
				const po = frappe.model.get_new_doc("Purchase Order");
				po.lr_indent_refs = (data.indents || []).join(", ");
				(data.items || []).forEach((it) => {
					const row = frappe.model.add_child(po, "items");
					Object.assign(row, it);
				});
				frappe.set_route("Form", "Purchase Order", po.name);
				show_reconciliation(data.reconciliation || []);
			});
		},
	});
}

function show_reconciliation(warn) {
	if (!warn.length) return;
	let msg = "<b>" + __("BOM reconciliation — components missing from indents:") + "</b><ul>";
	warn.forEach((w) => {
		msg += `<li>${w.model}: ${(w.missing_from_indent || []).join(", ")}</li>`;
	});
	msg += "</ul>";
	frappe.msgprint({ title: __("Check before ordering"), message: msg, indicator: "orange" });
}

frappe.listview_settings["Indent"] = {
	onload(listview) {
		listview.page.add_action_item(__("Create Purchase Order"), () => {
			const names = listview.get_checked_items().map((d) => d.name);
			if (!names.length) {
				frappe.msgprint(__("Select one or more Indents first."));
				return;
			}
			make_po(names);
		});
	},
	get_indicator(doc) {
		if (doc.workflow_state === "Ordered") return [__("Ordered"), "green", "workflow_state,=,Ordered"];
		if (doc.docstatus === 1) return [__("Approved"), "blue", "docstatus,=,1"];
		return [__("Draft"), "orange", "docstatus,=,0"];
	},
};
