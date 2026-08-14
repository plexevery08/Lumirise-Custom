// Stock Reconciliation -- blank physical stock-count sheet for warehouse users.
frappe.ui.form.on("Stock Reconciliation", {
	refresh(frm) {
		frm.add_custom_button(__("Download Stock Count Template"), () => download_template());
	},
});

function download_template() {
	frappe.call({
		method:
			"lumirise_custom.lumirise_custom.doctype.stock_reconciliation.stock_reconciliation.get_stock_reconciliation_template",
		freeze: true,
		freeze_message: __("Preparing template…"),
		callback(r) {
			if (!r.message) return;

			const blob = new Blob([r.message], { type: "text/csv;charset=utf-8;" });
			const url = URL.createObjectURL(blob);
			const link = document.createElement("a");
			link.href = url;
			link.download = "stock_reconciliation_template.csv";
			link.click();
			URL.revokeObjectURL(url);
		},
	});
}
