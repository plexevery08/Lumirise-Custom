// RM Price Book -- monthly RM purchase prices, uploaded by Purchase, MD-approved.
frappe.ui.form.on("RM Price Book", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Import Rows from File"), () => {
				if (!frm.doc.upload_file) {
					frappe.msgprint(__("Attach a CSV/Excel file in 'Price File' first (columns: item_code, rate)."));
					return;
				}
				frappe.call({
					method: "lumirise_custom.lumirise_custom.doctype.rm_price_book.rm_price_book.import_rows",
					args: { price_book: frm.doc.name, file_url: frm.doc.upload_file },
					freeze: true,
					freeze_message: __("Importing prices…"),
					callback() { frm.reload_doc(); },
				});
			});
		}
		if (frm.doc.docstatus === 1) {
			frm.set_intro(__("Approved — these raw-material rates are now used by costing/BOMs."), "green");
		}
	},
});
