// Lumirise desk-wide UI overrides.
// Loaded on every desk page via `app_include_js` (see hooks.py). Because this
// app loads after ERPNext, these assignments win over ERPNext's defaults.

// --- Item link display: show ONLY the Item Code -----------------------------
// ERPNext's default formatter (erpnext/public/js/utils.js -> add_link_title)
// renders Item link fields as "ItemCode: ItemName" whenever item_name differs
// from item_code. In child-table grids that merges both values into the single
// "Item Code" column (e.g. "Housing24: Housing24test"). Lumirise already shows
// Item Name in its own column, so we want the Item Code cell to show the code
// alone. Overriding the formatter to return the raw value removes the appended
// name everywhere Item links are shown (grids and link fields alike).
frappe.form.link_formatters["Item"] = function (value) {
	return value;
};

// --- Form navigation -------------------------------------------------------
// Add the client-requested Back button to every Desk form, including standard
// ERPNext and custom DocTypes. Frappe fires `form-refresh` after the form header
// is ready, so the button remains in the top form toolbar and is re-added when
// the form is refreshed.
$(document).on("form-refresh.lumirise-back-button", function (_event, frm) {
	if (!frm || !frm.page || frm.meta?.istable) {
		return;
	}

	frm.add_custom_button(__("Back"), function () {
		const go_back = function () {
			const previous_route = frappe.get_prev_route();
			if (previous_route && previous_route.length) {
				frappe.set_route(previous_route);
			} else {
				frappe.set_route("List", frm.doctype);
			}
		};

		if (frm.is_dirty()) {
			frappe.confirm(
				__("This form has unsaved changes. Leave without saving?"),
				go_back
			);
		} else {
			go_back();
		}
	});
});
