// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

frappe.ui.form.on("Line Daily Closing", {
	setup(frm) {
		// Line = a Warehouse, restricted to the ones configured under
		// Operations Settings → Production Lines.
		frm.set_query("production_line", () => ({
			query: "lumirise_custom.queries.line_warehouse_query",
		}));
	},
});
