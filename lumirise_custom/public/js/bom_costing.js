// Server-owned BOM costing preview. No formula is duplicated in JavaScript.

const LUMIRISE_BOM_COST_INPUTS = [
	"quantity",
	"custom_bom_type",
	"custom_conversion_cost",
	"custom_inward_transport_cost",
	"custom_factory_overheads",
	"custom_dollar_rate_fluctuations",
	"custom_interest_",
	"custom_miscellaneous",
	"custom_replacement",
	"custom_marketing_expenses",
	"custom_1k_moq_percentage",
	"custom_3k_moq_percentage",
	"custom_6k_moq_percentage",
	"custom_10k_moq_percentage",
];

const lumirise_bom_costing_events = {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Refresh Cost Preview"), () => {
				lumirise_preview_bom_costing(frm, true);
			});
		}
		lumirise_queue_bom_costing(frm);
	},
};

LUMIRISE_BOM_COST_INPUTS.forEach((fieldname) => {
	lumirise_bom_costing_events[fieldname] = lumirise_queue_bom_costing;
});

frappe.ui.form.on("BOM", lumirise_bom_costing_events);

frappe.ui.form.on("BOM Item", {
	items_add: lumirise_queue_bom_costing,
	items_remove: lumirise_queue_bom_costing,
	item_code: lumirise_queue_bom_costing,
	qty: lumirise_queue_bom_costing,
	bom_no: lumirise_queue_bom_costing,
});

function lumirise_queue_bom_costing(frm) {
	clearTimeout(frm.__lumirise_bom_costing_timer);
	frm.__lumirise_bom_costing_timer = setTimeout(() => lumirise_preview_bom_costing(frm), 300);
}

async function lumirise_preview_bom_costing(frm, show_alert = false) {
	if (!frm.doc || frm.__lumirise_bom_costing_running) return;
	frm.__lumirise_bom_costing_running = true;
	try {
		const response = await frappe.call({
			method: "lumirise_custom.costing.preview_bom_costing",
			args: { doc: frm.doc },
			freeze: show_alert,
			freeze_message: __("Resolving item and child-BOM costs..."),
		});
		const result = response.message || {};
		Object.entries(result.fields || {}).forEach(([fieldname, value]) => {
			if (!frm.fields_dict[fieldname] || frm.doc[fieldname] === value) return;
			frm.doc[fieldname] = value;
			frm.refresh_field(fieldname);
		});

		const rows = Object.fromEntries((frm.doc.items || []).map((row) => [row.name, row]));
		(result.items || []).forEach((result_row) => {
			const row = rows[result_row.name];
			if (!row) return;
			["rate", "amount", "custom_cost_source", "custom_cost_reference"].forEach(
				(fieldname) => {
					row[fieldname] = result_row[fieldname];
				}
			);
		});
		frm.refresh_field("items");
		if (show_alert)
			frappe.show_alert({ message: __("Cost preview refreshed"), indicator: "green" });
	} catch (error) {
		console.warn("Lumirise BOM costing preview failed", error);
	} finally {
		frm.__lumirise_bom_costing_running = false;
	}
}
