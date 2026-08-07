// Copyright (c) 2026, riddhi solanki and contributors
// For license information, please see license.txt

// Inbound Logistics cockpit — Dispatched -> In Transit -> Reached Warehouse.
// Each transition is a role-gated server method; the buttons only surface the
// right next action. IQC is then created MANUALLY via Create > IQC.

const LOG_METHOD =
	"lumirise_custom.lumirise_custom.doctype.inbound_logistics.inbound_logistics.";

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
		if (!frm.is_new() && frm.doc.docstatus === 1 && frm.doc.vehicle_gate_status !== "Approved") {
			frm.add_custom_button(__("Approve Vehicle Gate"), () => {
				return frappe.call({
					method: LOG_METHOD + "approve_gate",
					args: { docname: frm.doc.name }, freeze: true,
				}).then(() => frm.reload_doc());
			}, __("Inward Controls"));
		}
		if (!frm.is_new() && frm.doc.docstatus === 1 && frm.doc.document_verification_status !== "Verified") {
			frm.add_custom_button(__("Verify Documents"), () => {
				frappe.prompt([
					{ fieldname: "exception", label: __("Exception (leave blank to verify)"), fieldtype: "Small Text" },
				], (v) => {
					return frappe.call({
						method: LOG_METHOD + "verify_documents",
						args: { docname: frm.doc.name, exception: v.exception }, freeze: true,
					}).then(() => frm.reload_doc());
				}, __("Verify Inward Documents"), __("Save"));
			}, __("Inward Controls"));
		}
		if (frm.doc.docstatus !== 1) {
			return; // transitions act on the submitted consignment
		}

		const status = frm.doc.status;

		if (status === "Dispatched") {
			frm.set_intro(__("Consignment dispatched. Mark it In Transit once it leaves."), "blue");
			frm.add_custom_button(__("Mark In Transit"), () =>
				log_run(frm, "mark_in_transit", __("Updating…"))
			).addClass("btn-primary");
		} else if (status === "In Transit") {
			frm.set_intro(__("In transit. Mark Reached Warehouse when it arrives at the dock."), "orange");
			frm.add_custom_button(__("Mark Reached Warehouse"), () =>
				log_run(frm, "mark_reached", __("Updating…"))
			).addClass("btn-primary");
		} else if (status === "Reached Warehouse") {
			frm.set_intro(__("Reached the warehouse. Raise IQC to inspect the consignment."), "green");
		}

		// Next-stage doc — manual, only after the goods have arrived.
		if (status === "Reached Warehouse") {
			frm.add_custom_button(__("IQC"), () => {
				frappe.model.open_mapped_doc({
					method: "lumirise_custom.chain.make_iqc",
					frm: frm,
				});
			}, __("Create"));
			frm.add_custom_button(__("Generate RM Package / LPN"), () => {
				const items = (frm.doc.items || []).filter((r) => r.item_code);
				if (!items.length) {
					frappe.msgprint(__("Add at least one inbound item first."));
					return;
				}
				frappe.prompt([
					{ fieldname: "item_code", label: __("Item"), fieldtype: "Select", options: items.map((r) => r.item_code).join("\n"), reqd: 1 },
					{ fieldname: "quantity", label: __("Package Quantity"), fieldtype: "Float", reqd: 1 },
					{ fieldname: "supplier_lot", label: __("Supplier Lot / Reference"), fieldtype: "Data" },
				], (v) => frappe.call({
					method: "lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.create_from_inbound",
					args: { inbound_logistics: frm.doc.name, item_code: v.item_code, quantity: v.quantity, supplier_lot: v.supplier_lot },
					freeze: true, freeze_message: __("Creating native Batch and LPN…"),
				}).then((r) => {
					if (r.message) frappe.set_route("Form", "RM Package", r.message.name);
				}), __("Generate RM Package"), __("Create"));
			}, __("Barcode"));
		}
	},
});
