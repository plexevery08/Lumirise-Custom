# Programmatically create the lumirise_custom DocTypes (developer_mode writes the
# JSON + controller stubs to disk). Idempotent: existing DocTypes are skipped.
#
# Run:  bench --site site.com execute lumirise_custom.demo.build_doctypes.execute
#
# Mirrors the Focus 9 process steps that standard ERPNext lacks:
#   Material Planning (cockpit) -> Indent -> Vendor PDI -> Inbound Logistics
#   -> IQC -> [standard Purchase Receipt = GRN] ; and Customer PDI (pre-dispatch).

import frappe

MODULE = "Lumirise Custom"


def _f(fieldname, fieldtype, label=None, **kw):
    d = {"fieldname": fieldname, "fieldtype": fieldtype, "label": label or fieldname.replace("_", " ").title()}
    d.update(kw)
    return d


def _make(name, fields, *, istable=0, submittable=0, autoname=None, naming_rule=None,
          title_field=None, track_changes=1):
    if frappe.db.exists("DocType", name):
        print("  skip (exists):", name)
        return
    doc = {
        "doctype": "DocType", "name": name, "module": MODULE, "custom": 0,
        "istable": istable, "is_submittable": submittable,
        "editable_grid": 1, "track_changes": track_changes,
        "fields": fields,
        "permissions": [] if istable else [{
            "role": "System Manager", "read": 1, "write": 1, "create": 1,
            "delete": 1, "submit": submittable, "cancel": submittable,
            "amend": submittable, "report": 1, "export": 1, "print": 1, "share": 1, "email": 1,
        }],
    }
    if autoname:
        doc["autoname"] = autoname
    if naming_rule:
        doc["naming_rule"] = naming_rule
    if title_field:
        doc["title_field"] = title_field
    frappe.get_doc(doc).insert(ignore_permissions=True)
    print("  created:", name)


def execute():
    # ----------------------------------------------------------- CHILD TABLES
    _make("Indent Item", [
        _f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
        _f("item_name", "Data", "Item Name", fetch_from="item_code.item_name", read_only=1),
        _f("qty", "Float", "Qty", reqd=1, in_list_view=1),
        _f("uom", "Link", "UOM", options="UOM", default="Nos", in_list_view=1),
        _f("required_date", "Date", "Required Date"),
        _f("source_bom", "Link", "Source BOM", options="BOM"),
        _f("model", "Data", "Model"),
        _f("for_sales_order", "Link", "For Sales Order", options="Sales Order", in_list_view=1),
        # NOTE: deliberately NO rate field -- rate appears only at PO (mirrors Focus).
    ], istable=1)

    _make("Vendor PDI Item", [
        _f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
        _f("po_qty", "Float", "PO Qty", read_only=1, in_list_view=1),
        _f("approved_qty", "Float", "Approved Qty", reqd=1, in_list_view=1,
           description="Cannot exceed PO Qty (Focus rule)."),
        _f("container_no", "Data", "Container No", in_list_view=1),
        _f("pi_number", "Data", "PI Number"),
        _f("remarks", "Small Text", "Remarks"),
    ], istable=1)

    _make("Inbound Logistics Item", [
        _f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
        _f("qty", "Float", "Qty", reqd=1, in_list_view=1),
        _f("remarks", "Small Text", "Remarks"),
    ], istable=1)

    _make("IQC Item", [
        _f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
        _f("received_qty", "Float", "Received Qty", in_list_view=1),
        _f("accepted_qty", "Float", "Accepted Qty", reqd=1, in_list_view=1),
        _f("rejected_qty", "Float", "Rejected Qty", in_list_view=1),
        _f("reject_reason", "Data", "Reject Reason"),
        _f("disposition", "Select", "Disposition",
           options="\nReturn to Vendor\nReplace\nScrap"),
    ], istable=1)

    _make("Customer PDI Check", [
        _f("parameter", "Data", "Parameter", reqd=1, in_list_view=1),
        _f("result", "Select", "Result", options="Accepted\nRejected",
           default="Accepted", in_list_view=1),
        _f("remarks", "Data", "Remarks", in_list_view=1),
    ], istable=1)

    _make("Material Planning FG", [
        _f("sales_order", "Link", "Sales Order", options="Sales Order", reqd=1, in_list_view=1),
        _f("fg_item", "Link", "FG Item", options="Item", reqd=1, in_list_view=1),
        _f("bom", "Link", "BOM", options="BOM"),
        _f("aso_qty", "Float", "Order Qty (ASO)", in_list_view=1),
        _f("fg_available", "Float", "Available in FG", in_list_view=1),
        _f("required_qty", "Float", "Required Qty", in_list_view=1,
           description="Order qty minus FG already available."),
    ], istable=1)

    _make("Material Planning Item", [
        _f("sales_order", "Link", "Sales Order", options="Sales Order", in_list_view=1),
        _f("fg_item", "Link", "FG", options="Item"),
        _f("component_item", "Link", "Component", options="Item", reqd=1, in_list_view=1),
        _f("required_qty", "Float", "Required", in_list_view=1),
        _f("rm_available", "Float", "RM Available", in_list_view=1),
        _f("blocked_for_other_so", "Float", "Blocked (other SOs)", in_list_view=1,
           description="Reserved by submitted Work Orders for other orders."),
        _f("available_after_blocking", "Float", "Available After Blocking", in_list_view=1),
        _f("pending_po", "Float", "Pending PO"),
        _f("pending_pdi", "Float", "Pending PDI"),
        _f("pending_iqc", "Float", "Pending IQC"),
        _f("indent_balance", "Float", "Indent Balance"),
        _f("to_be_ordered", "Float", "To Be Ordered", in_list_view=1,
           description="Net shortage to procure (positive = raise indent)."),
    ], istable=1)

    # --------------------------------------------------------- PARENT DOCTYPES
    _make("Indent", [
        _f("indent_date", "Date", "Indent Date", default="Today", reqd=1),
        _f("branch", "Data", "Branch", default="Lumirise"),
        _f("indent_type", "Select", "Indent Type", options="Purchase\nService", default="Purchase"),
        _f("col1", "Column Break", None),
        # source_planning is added after Material Planning exists. It is a plain
        # Data field (NOT a Link) on purpose -- a Link here + created_indent on
        # Material Planning forms a circular link that blocks deleting either doc.
        _f("source_sales_order", "Link", "Source Sales Order", options="Sales Order", read_only=1),
        _f("workflow_state", "Link", "Status", options="Workflow State", read_only=1, in_list_view=1),
        _f("sec_items", "Section Break", "Items"),
        _f("items", "Table", "Indent Items", options="Indent Item", reqd=1),
        _f("amended_from", "Link", "Amended From", options="Indent", read_only=1, no_copy=1, print_hide=1),
    ], submittable=1, autoname="IND-.YYYY.-.#####", naming_rule="Expression")

    _make("Vendor PDI", [
        _f("purchase_order", "Link", "Purchase Order", options="Purchase Order", reqd=1, in_list_view=1),
        _f("supplier", "Link", "Supplier", options="Supplier",
           fetch_from="purchase_order.supplier", read_only=1, in_list_view=1),
        _f("mode", "Select", "Mode", options="Domestic\nImport", default="Domestic"),
        _f("col1", "Column Break", None),
        _f("pdi_date", "Date", "PDI Date", default="Today"),
        _f("pdi_attachment", "Attach", "Vendor PDI Report"),
        _f("sec_items", "Section Break", "Items"),
        _f("items", "Table", "Items", options="Vendor PDI Item", reqd=1),
        _f("amended_from", "Link", "Amended From", options="Vendor PDI", read_only=1, no_copy=1, print_hide=1),
    ], submittable=1, autoname="VPDI-.YYYY.-.#####", naming_rule="Expression")

    _make("Inbound Logistics", [
        _f("vendor_pdi", "Link", "Vendor PDI", options="Vendor PDI", reqd=1, in_list_view=1),
        _f("purchase_order", "Link", "Purchase Order", options="Purchase Order",
           fetch_from="vendor_pdi.purchase_order", read_only=1),
        _f("mode", "Select", "Mode", options="Road\nSea", default="Road"),
        _f("col1", "Column Break", None),
        _f("lr_number", "Data", "LR Number"),
        _f("lr_date", "Date", "LR Date", default="Today"),
        _f("vehicle_no", "Data", "Vehicle No"),
        _f("transporter", "Data", "Transporter"),
        _f("container_no", "Data", "Container No"),
        _f("sec_items", "Section Break", "Items"),
        _f("items", "Table", "Items", options="Inbound Logistics Item", reqd=1),
        _f("amended_from", "Link", "Amended From", options="Inbound Logistics", read_only=1, no_copy=1, print_hide=1),
    ], submittable=1, autoname="LOG-.YYYY.-.#####", naming_rule="Expression")

    _make("IQC", [
        _f("inbound_logistics", "Link", "Inbound Logistics", options="Inbound Logistics", reqd=1, in_list_view=1),
        _f("purchase_order", "Link", "Purchase Order", options="Purchase Order",
           fetch_from="inbound_logistics.purchase_order", read_only=1, in_list_view=1),
        _f("mode", "Select", "Mode", options="Domestic\nImport", default="Domestic"),
        _f("col1", "Column Break", None),
        _f("iqc_date", "Date", "IQC Date", default="Today"),
        _f("sampling_plan", "Data", "Sampling Plan"),
        _f("result", "Select", "Result", options="Accepted\nPartial\nRejected", default="Accepted", in_list_view=1),
        _f("sec_items", "Section Break", "Items"),
        _f("items", "Table", "Items", options="IQC Item", reqd=1),
        _f("amended_from", "Link", "Amended From", options="IQC", read_only=1, no_copy=1, print_hide=1),
    ], submittable=1, autoname="IQC-.YYYY.-.#####", naming_rule="Expression")

    _make("Customer PDI", [
        _f("sales_order", "Link", "Sales Order", options="Sales Order", reqd=1, in_list_view=1),
        _f("customer", "Link", "Customer", options="Customer",
           fetch_from="sales_order.customer", read_only=1, in_list_view=1),
        _f("fg_item", "Link", "FG Item", options="Item", reqd=1),
        _f("sampled_qty", "Float", "Sampled Qty", default=20),
        _f("col1", "Column Break", None),
        _f("source_warehouse", "Link", "Source Warehouse", options="Warehouse", default="Finished Goods - L"),
        _f("pdi_warehouse", "Link", "PDI Warehouse", options="Warehouse", default="Customer PDI - L"),
        _f("video_recording", "Attach", "Video Recording"),
        _f("customer_signoff", "Select", "Customer Sign-off", options="\nPass\nFail", in_list_view=1),
        _f("sec_checks", "Section Break", "Inspection Checks"),
        _f("checks", "Table", "Checks", options="Customer PDI Check"),
        _f("amended_from", "Link", "Amended From", options="Customer PDI", read_only=1, no_copy=1, print_hide=1),
    ], submittable=1, autoname="CPDI-.YYYY.-.#####", naming_rule="Expression")

    _make("Material Planning", [
        _f("planning_date", "Date", "Planning Date", default="Today", reqd=1),
        _f("branch", "Data", "Branch", default="Lumirise"),
        _f("due_date", "Date", "Due Date"),
        _f("col1", "Column Break", None),
        # Data, not Link -- see the source_planning note on Indent above.
        _f("created_indent", "Data", "Created Indent", read_only=1),
        _f("created_work_orders", "Small Text", "Created Work Orders", read_only=1),
        _f("workflow_state", "Data", "Status", read_only=1, hidden=1),
        _f("sec_fg", "Section Break", "FG / Sales Order Plan"),
        _f("fg_plan", "Table", "FG Plan", options="Material Planning FG"),
        _f("sec_comp", "Section Break", "Component Requirement (reservation / blocking)"),
        _f("components", "Table", "Components", options="Material Planning Item"),
        _f("amended_from", "Link", "Amended From", options="Material Planning", read_only=1, no_copy=1, print_hide=1),
    ], submittable=1, autoname="MP-.YYYY.-.#####", naming_rule="Expression")

    # Now that Material Planning exists, add the source_planning back-reference
    # onto Indent -- as Data (NOT a Link) to avoid the circular-link delete deadlock.
    _add_field_after("Indent", "indent_type",
        _f("source_planning", "Data", "Source Planning", read_only=1))

    frappe.db.commit()
    print("DocTypes built.")


def _add_field_after(doctype, after_fieldname, field):
    doc = frappe.get_doc("DocType", doctype)
    if any(f.fieldname == field["fieldname"] for f in doc.fields):
        print(f"  skip field (exists): {doctype}.{field['fieldname']}")
        return
    row = doc.append("fields", field)
    # move the appended row to just after `after_fieldname`
    idx = next((i for i, f in enumerate(doc.fields) if f.fieldname == after_fieldname), None)
    if idx is not None:
        doc.fields.remove(row)
        doc.fields.insert(idx + 1, row)
        for i, f in enumerate(doc.fields, start=1):
            f.idx = i
    doc.save(ignore_permissions=True)
    print(f"  added field: {doctype}.{field['fieldname']}")
