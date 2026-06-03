// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Indent form: convert THIS indent into Purchase Order(s).
// Indent list: select MANY approved indents -> one consolidated PO per supplier
// (the Focus 9 "merge indents for volume discounts" behaviour).

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
		method: "lumirise_custom.lumirise_custom.doctype.indent.indent.make_po_from_indents",
		args: { indents },
		freeze: true,
		freeze_message: __("Consolidating indents into Purchase Order(s)..."),
		callback(r) {
			if (!r.message) return;
			const pos = (r.message.purchase_orders || [])
				.map((p) => `<a href="/app/purchase-order/${encodeURIComponent(p)}">${p}</a>`)
				.join(", ");
			let msg = __("Created Purchase Order(s): {0}", [pos || "—"]);
			const warn = r.message.reconciliation || [];
			if (warn.length) {
				msg += "<hr><b>" + __("BOM reconciliation — components missing from indents:") + "</b><ul>";
				warn.forEach((w) => {
					msg += `<li>${w.model}: ${(w.missing_from_indent || []).join(", ")}</li>`;
				});
				msg += "</ul>";
			} else {
				msg += "<br><span style='color:green'>" + __("BOM reconciliation: nothing missing.") + "</span>";
			}
			frappe.msgprint({ title: __("Purchase Orders"), message: msg, indicator: "green" });
		},
	});
}

frappe.listview_settings["Indent"] = {
	onload(listview) {
		listview.page.add_action_item(__("Create Purchase Order(s)"), () => {
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
