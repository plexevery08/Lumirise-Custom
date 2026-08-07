// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Inbound Logistics cockpit — Dispatched -> In Transit -> Reached Warehouse.
// Each transition is a role-gated server method; the buttons only surface the
// right next action. IQC is then created MANUALLY via Create > IQC.

const LOG_METHOD = "lumirise_custom.lumirise_custom.doctype.inbound_logistics.inbound_logistics.";

function log_run(frm, method, freeze_message) {
	const call = () =>
		frappe
			.call({
				method: LOG_METHOD + method,
				args: { docname: frm.doc.name },
				freeze: true,
				freeze_message: freeze_message || __("Working…"),
			})
			.then((r) => {
				frm.reload_doc();
				if (r && r.message) {
					frappe.show_alert({ message: __("Done"), indicator: "green" });
				}
			});
	if (frm.is_dirty()) {
		return frm.save("Update").then(call);
	}
	return call();
}

frappe.ui.form.on("Inbound Logistics", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return; // transitions act on the submitted consignment
		}

		const status = frm.doc.status;

		if (status === "Dispatched") {
			frm.set_intro(
				__("Consignment dispatched. Mark it In Transit once it leaves."),
				"blue"
			);
			frm.add_custom_button(__("Mark In Transit"), () =>
				log_run(frm, "mark_in_transit", __("Updating…"))
			).addClass("btn-primary");
		} else if (status === "In Transit") {
			frm.set_intro(
				__("In transit. Mark Reached Warehouse when it arrives at the dock."),
				"orange"
			);
			frm.add_custom_button(__("Mark Reached Warehouse"), () =>
				log_run(frm, "mark_reached", __("Updating…"))
			).addClass("btn-primary");
		} else if (status === "Reached Warehouse") {
			frm.set_intro(
				__("Reached the warehouse. Raise IQC to inspect the consignment."),
				"green"
			);
		}

		// Next-stage doc — manual, only after the goods have arrived.
		if (status === "Reached Warehouse") {
			frm.add_custom_button(
				__("Generate RM Package Labels"),
				() => {
					const items = (frm.doc.items || []).map((r) => r.item_code).filter(Boolean);
					frappe.prompt(
						[
							{
								fieldname: "item_code",
								label: __("Item"),
								fieldtype: "Select",
								options: items.join("\n"),
								reqd: 1,
							},
							{
								fieldname: "package_count",
								label: __("Number of Packages"),
								fieldtype: "Int",
								reqd: 1,
								default: 1,
							},
							{
								fieldname: "total_qty",
								label: __("Total Qty in These Packages (Stock UOM)"),
								fieldtype: "Float",
								reqd: 1,
								description: __(
									"Enter the quantity shown in the Item's Stock UOM."
								),
							},
							{
								fieldname: "package_type",
								label: __("Package Type"),
								fieldtype: "Select",
								options: "Carton\nPallet\nDrum\nBag\nCrate\nOther",
								default: "Carton",
								reqd: 1,
							},
							{
								fieldname: "supplier_lot",
								label: __("Supplier Lot / Heat No."),
								fieldtype: "Data",
							},
							{
								fieldname: "manufacturing_date",
								label: __("Manufacturing Date"),
								fieldtype: "Date",
							},
							{
								fieldname: "expiry_date",
								label: __("Expiry Date"),
								fieldtype: "Date",
							},
						],
						(v) =>
							frappe
								.call({
									method: "lumirise_custom.rm_barcode.create_receiving_packages",
									args: { inbound_logistics: frm.doc.name, packages: [v] },
									freeze: true,
									freeze_message: __("Generating package labels…"),
								})
								.then((r) => {
									frappe.show_alert({
										message: __("Created {0} labels", [
											r.message.created.length,
										]),
										indicator: "green",
									});
									frappe.set_route("List", "RM Receiving Package", {
										inbound_logistics: frm.doc.name,
									});
								}),
						__("Generate Lumirise RM Labels"),
						__("Generate")
					);
				},
				__("Barcode")
			);
			frm.add_custom_button(
				__("IQC"),
				() => {
					frappe.model.open_mapped_doc({
						method: "lumirise_custom.chain.make_iqc",
						frm: frm,
					});
				},
				__("Create")
			);
		}
	},
});
