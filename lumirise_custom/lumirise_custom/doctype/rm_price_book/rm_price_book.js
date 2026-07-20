// RM Price Book -- monthly RM purchase prices, uploaded by Purchase, MD-approved.
frappe.ui.form.on("RM Price Book", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Import Rows from File"), () => import_prices(frm));
		}
		frm.add_custom_button(__("Download Template"), () => download_template());

		if (frm.doc.docstatus === 1) {
			frm.set_intro(__("Approved — these raw-material rates are now used by costing/BOMs."), "green");
		}
	},
});

// One button, whatever state the form is in: it saves the draft, collects the file,
// imports the rows, and leaves the user on a saved draft to review.
//
// Why it saves first: import_rows() runs on the server and needs a real docname to
// load and write rows into, and Frappe cannot attach a file to an unsaved parent.
// Making the user discover that ordering ("save, then attach, then import") is what
// this replaces -- Purchase should just press the button.
async function import_prices(frm) {
	if (frm.is_new() || frm.is_dirty()) {
		await frm.save();
	}

	// File already attached (or re-importing the same one) -- go straight to import.
	if (frm.doc.upload_file) {
		run_import(frm, frm.doc.upload_file);
		return;
	}

	new frappe.ui.FileUploader({
		doctype: frm.doctype,
		docname: frm.doc.name,
		folder: "Home/Attachments",
		restrictions: { allowed_file_types: [".csv", ".xlsx", ".xls"] },
		on_success: async (file_doc) => {
			await frm.set_value("upload_file", file_doc.file_url);
			await frm.save();
			run_import(frm, file_doc.file_url);
		},
	});
}

function run_import(frm, file_url) {
	frappe.call({
		method: "lumirise_custom.lumirise_custom.doctype.rm_price_book.rm_price_book.import_rows",
		args: { price_book: frm.doc.name, file_url: file_url },
		freeze: true,
		freeze_message: __("Importing prices…"),
		callback() {
			frm.reload_doc();
		},
	});
}

function download_template() {
	frappe.call({
		method: "lumirise_custom.lumirise_custom.doctype.rm_price_book.rm_price_book.get_rm_price_template",
		callback(r) {
			const blob = new Blob([r.message || ""], { type: "text/csv" });
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = "rm_price_book_template.csv";
			a.click();
			URL.revokeObjectURL(url);
		},
	});
}
