// Poster-aligned inward cockpit. Every state change is revalidated on the server.

const LOG_METHOD =
	"lumirise_custom.lumirise_custom.doctype.inbound_logistics.inbound_logistics.";
const INWARD_METHOD = "lumirise_custom.inward_process.";

function inward_call(frm, method, args, freeze_message) {
	const run = () =>
		frappe
			.call({
				method: method.includes(".") ? method : INWARD_METHOD + method,
				args: Object.assign({ docname: frm.doc.name }, args || {}),
				freeze: true,
				freeze_message: freeze_message || __("Working…"),
			})
			.then((r) => {
				frm.reload_doc();
				if (r && r.message) {
					frappe.show_alert({ message: __("Checkpoint recorded"), indicator: "green" });
				}
				return r;
			});
	if (frm.is_dirty()) {
		return frm.save("Update").then(run);
	}
	return run();
}

function prompt_and_call(frm, title, fields, method, freeze_message) {
	frappe.prompt(
		fields,
		(values) => inward_call(frm, method, values, freeze_message),
		title,
		__("Continue")
	);
}

function add_package_button(frm) {
	const items = (frm.doc.items || []).filter((row) => row.item_code);
	frm.add_custom_button(
		__("Generate Carton / Pallet LPN"),
		() => {
			frappe.prompt(
				[
					{
						fieldname: "item_code",
						label: __("Item"),
						fieldtype: "Select",
						options: items.map((row) => row.item_code).join("\n"),
						reqd: 1,
					},
					{
						fieldname: "quantity",
						label: __("Carton / Pallet Quantity"),
						fieldtype: "Float",
						reqd: 1,
					},
					{
						fieldname: "supplier_lot",
						label: __("Supplier Lot / Reference"),
						fieldtype: "Data",
					},
				],
				(values) =>
					frappe
						.call({
							method:
								"lumirise_custom.lumirise_custom.doctype.rm_package.rm_package.create_from_inbound",
							args: Object.assign({ inbound_logistics: frm.doc.name }, values),
							freeze: true,
							freeze_message: __("Generating package identity…"),
						})
						.then((r) => {
							if (r.message) {
								frappe.set_route("Form", "RM Package", r.message.name);
							}
						}),
				__("Generate RM Package / LPN"),
				__("Create")
			);
		},
		__("Barcode")
	);
}

frappe.ui.form.on("Inbound Logistics", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) {
			return;
		}

		const stage = frm.doc.inward_stage || "Vehicle In Transit";
		frm.set_intro(__("Current inward checkpoint: {0}", [stage]), stage === "Closed" ? "green" : "blue");

		if (frm.doc.status === "Dispatched") {
			frm.add_custom_button(__("Mark In Transit"), () =>
				inward_call(frm, LOG_METHOD + "mark_in_transit", {}, __("Updating transit…"))
			);
		}
		if (["Dispatched", "In Transit"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Register Vehicle Arrival"), () =>
				inward_call(frm, "register_vehicle_arrival", {}, __("Registering arrival…"))
			).addClass("btn-primary");
		}

		if (frm.doc.status === "Reached Warehouse" && !frm.doc.arrival_registered_on) {
			frm.add_custom_button(__("Register Vehicle Arrival"), () =>
				inward_call(frm, "register_vehicle_arrival", {}, __("Registering arrival…"))
			).addClass("btn-primary");
		}

		if (stage === "Awaiting Gate Approval") {
			frm.add_custom_button(__("Approve Vehicle Entry"), () =>
				inward_call(frm, "approve_vehicle_entry", {}, __("Approving entry…"))
			).addClass("btn-primary");
			frm.add_custom_button(__("Reject Vehicle Entry"), () =>
				prompt_and_call(
					frm,
					__("Reject Vehicle Entry"),
					[{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 }],
					"reject_vehicle_entry"
				)
			);
		}

		if (frm.doc.vehicle_gate_status === "Approved" && !frm.doc.gate_verified_on) {
			frm.add_custom_button(
				__("Verify Gate Stamp"),
				() =>
					prompt_and_call(
						frm,
						__("Security Gate Verification"),
						[
							{
								fieldname: "stamp_reference",
								label: __("Gate Stamp / Signature Reference"),
								fieldtype: "Data",
								reqd: 1,
							},
							{
								fieldname: "gate_invoice_attachment",
								label: __("Gate-stamped Invoice"),
								fieldtype: "Attach",
							},
						],
						"verify_gate_entry"
					),
				__("Inward Controls")
			);
		}

		if (frm.doc.gate_verified_on && frm.doc.document_verification_status !== "Verified") {
			frm.add_custom_button(
				__("Verify Inward Documents"),
				() =>
					prompt_and_call(
						frm,
						__("Document Checklist — no verified documents, no unloading"),
						[
							{ fieldname: "invoice_verified", label: __("Invoice Received & Verified"), fieldtype: "Check" },
							{ fieldname: "packing_list_matched", label: __("Packing List Received & Matched"), fieldtype: "Check" },
							{ fieldname: "waybill_verified", label: __("Waybill / LR Received & Verified"), fieldtype: "Check" },
							{ fieldname: "other_documents_received", label: __("Other Supporting Documents Received"), fieldtype: "Check" },
							{ fieldname: "documents_forwarded_to_manager", label: __("Forwarded to Inward Manager"), fieldtype: "Check" },
							{ fieldname: "document_bundle_attachment", label: __("Scanned Document Bundle"), fieldtype: "Attach" },
							{ fieldname: "exception", label: __("Exception (blocks unloading)"), fieldtype: "Small Text" },
						],
						"verify_documents"
					),
				__("Inward Controls")
			);
		}

		if (frm.doc.document_verification_status === "Verified" && !frm.doc.iqc_reference) {
			frm.add_custom_button(__("Raise Mandatory IQC Task"), () =>
				inward_call(frm, "raise_iqc_task", {}, __("Creating IQC and Quality task…"))
			).addClass("btn-primary");
		}

		if (frm.doc.iqc_reference) {
			frm.add_custom_button(__("Open IQC"), () =>
				frappe.set_route("Form", "IQC", frm.doc.iqc_reference)
			);
		}

		if (frm.doc.iqc_reference && [null, "", "Pending"].includes(frm.doc.unloading_status)) {
			frm.add_custom_button(__("Start Controlled Unloading"), () =>
				inward_call(frm, "start_unloading", {}, __("Starting unloading…"))
			).addClass("btn-primary");
		}
		if (frm.doc.unloading_status === "In Progress") {
			frm.add_custom_button(__("Complete Unloading"), () =>
				inward_call(frm, "complete_unloading", {}, __("Completing unloading…"))
			).addClass("btn-primary");
		}
		if (frm.doc.unloading_status === "Completed" && !frm.doc.physical_verified_on) {
			frm.add_custom_button(__("Record Physical Verification"), () =>
				prompt_and_call(
					frm,
					__("Packing-list Quantity / Damage Check"),
					[
						{
							fieldname: "status",
							label: __("Result"),
							fieldtype: "Select",
							options: "Matched\nShort Quantity\nExcess Quantity\nDamaged Material\nTransport Damage\nMultiple Exceptions",
							reqd: 1,
						},
						{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" },
					],
					"record_physical_verification",
					__("Recording check…")
				)
			).addClass("btn-primary");
		}
		if (frm.doc.physical_verified_on && !frm.doc.invoice_price_verified) {
			frm.add_custom_button(__("Verify Invoice Price vs PO"), () =>
				inward_call(frm, "verify_invoice_price", {}, __("Recording price check…"))
			);
		}

		if (
			frm.doc.iqc_reference &&
			frm.doc.invoice_price_verified &&
			!frm.doc.storage_authorized
		) {
			frm.add_custom_button(__("Authorize Storage & Allocate Rack"), () =>
				prompt_and_call(
					frm,
					__("Storage Authorization — requires submitted IQC Pass"),
					[
						{
							fieldname: "rack_warehouse",
							label: __("Allocated Rack / Bay"),
							fieldtype: "Link",
							options: "Warehouse",
							reqd: 1,
						},
					],
					"authorize_storage"
				)
			).addClass("btn-primary");
		}

		if (frm.doc.storage_authorized) {
			add_package_button(frm);
		}
		if (frm.doc.storage_authorized && !frm.doc.purchase_receipt && frm.doc.iqc_reference) {
			frm.add_custom_button(
				__("GRN (Purchase Receipt)"),
				() =>
					frappe.model.open_mapped_doc({
						method: "lumirise_custom.chain.make_grn",
						source_name: frm.doc.iqc_reference,
						frm,
					}),
				__("Create")
			);
		}

		if (frm.doc.purchase_receipt) {
			frm.add_custom_button(__("Open GRN"), () =>
				frappe.set_route("Form", "Purchase Receipt", frm.doc.purchase_receipt)
			);
			if (!frm.doc.outward_accepted) {
				frm.add_custom_button(__("RM Stores Accept Physical Count"), () =>
					prompt_and_call(
						frm,
						__("RM / Outward Acceptance"),
						[
							{ fieldname: "signed_packing_list", label: __("Signed Packing List"), fieldtype: "Attach", reqd: 1 },
						],
						"accept_at_rm_store"
					)
				);
			}
			if (!frm.doc.documents_handed_over) {
				frm.add_custom_button(__("Hand Over Documents to Purchase"), () =>
					prompt_and_call(
						frm,
						__("Purchase Document Handover"),
						[
							{ fieldname: "handover_bundle_attachment", label: __("GRN + Invoice + LR + IQC Bundle"), fieldtype: "Attach", reqd: 1 },
						],
						"handover_documents"
					)
				);
			}
		}

		if (frm.doc.outward_accepted && !frm.doc.erp_entry_verified) {
			frm.add_custom_button(__("Verify Rack Stock Note & ERP"), () =>
				prompt_and_call(
					frm,
					__("End-of-day Rack / ERP Cross-check"),
					[
						{ fieldname: "stock_note_reference", label: __("Rack Stock Note Reference"), fieldtype: "Data", reqd: 1 },
						{ fieldname: "stock_note_attachment", label: __("Rack Stock Note"), fieldtype: "Attach" },
					],
					"verify_putaway_and_erp"
				)
			);
		}
		if (frm.doc.erp_entry_verified && frm.doc.documents_handed_over && !frm.doc.final_signoff) {
			frm.add_custom_button(__("Complete Final Inward Sign-off"), () =>
				inward_call(frm, "close_inward", {}, __("Closing inward process…"))
			).addClass("btn-primary");
		}
	},
});
