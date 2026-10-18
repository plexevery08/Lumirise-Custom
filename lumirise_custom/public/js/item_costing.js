// Server-owned Item costing preview. The same Python function runs again on save.

const LUMIRISE_ITEM_COST_INPUTS = [
	"custom_price_in_rmb",
	"custom_rmb_to_inr_rate",
	"custom_custom_duty",
];

const lumirise_item_costing_events = {
	refresh(frm) {
		lumirise_queue_item_costing(frm);
	},
};

LUMIRISE_ITEM_COST_INPUTS.forEach((fieldname) => {
	lumirise_item_costing_events[fieldname] = lumirise_queue_item_costing;
});

frappe.ui.form.on("Item", lumirise_item_costing_events);

function lumirise_queue_item_costing(frm) {
	clearTimeout(frm.__lumirise_item_costing_timer);
	frm.__lumirise_item_costing_timer = setTimeout(() => lumirise_preview_item_costing(frm), 250);
}

async function lumirise_preview_item_costing(frm) {
	if (!frm.doc || frm.__lumirise_item_costing_running) return;
	frm.__lumirise_item_costing_running = true;
	try {
		const response = await frappe.call({
			method: "lumirise_custom.costing.preview_item_costing",
			args: { doc: frm.doc },
			freeze: false,
		});
		Object.entries(response.message || {}).forEach(([fieldname, value]) => {
			if (!frm.fields_dict[fieldname] || frm.doc[fieldname] === value) return;
			frm.doc[fieldname] = value;
			frm.refresh_field(fieldname);
		});
	} catch (error) {
		console.warn("Lumirise Item costing preview failed", error);
	} finally {
		frm.__lumirise_item_costing_running = false;
	}
}
