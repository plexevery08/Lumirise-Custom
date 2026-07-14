# RM Stock & Reservation Tracker — one screen for the full life of a raw material:
# what is on hand, how much is committed to Work Orders (and to which WO -> which
# Sales Order), what is still coming in (Indent -> PO -> Vendor PDI -> In Transit
# -> IQC), and the resulting positive Shortfall-to-Order. Three views via the
# "View" filter:
#
#   Summary by Item            -> one row per RM: on-hand / committed / incoming /
#                                 shortfall, summed across ALL stock warehouses
#                                 (so multi-warehouse stock is never missed).
#   Reservation Detail (WO->SO)-> one row per (item x open Work Order): how much
#                                 each WO holds, its FG, its Sales Order, customer.
#   Incoming Pipeline Detail   -> one row per incoming document at its live stage.
#
# The pipeline numbers reuse the SAME helpers as the Material Planning cockpit, so
# this report and the planner can never disagree.

import frappe
from frappe import _
from frappe.utils import flt

from lumirise_custom.lumirise_custom.doctype.material_planning.material_planning import (
    _open_po, _pending_pdi, _in_transit, _pending_iqc, _indent_balance,
)

CLOSED_WO = ("Completed", "Stopped", "Closed")

# Always-on hard scope: this is the RAW-MATERIAL tracker, so it only ever shows items
# in the raw-material item groups. Both groups exist on the Lumirise masters and real
# BOM components are split across them. Edit this tuple if the RM group naming changes.
RM_ITEM_GROUPS = ("Raw Material", "LED Raw Material")


def _effective_rm_groups(filters):
    """The RM item groups this run should show. Always restricted to RM_ITEM_GROUPS
    (hard scope); a user-picked Item Group narrows further but only WITHIN the RM set
    (picking a non-RM group yields nothing, by design)."""
    ig = filters.get("item_group")
    if ig:
        return [ig] if ig in RM_ITEM_GROUPS else []
    return list(RM_ITEM_GROUPS)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    view = filters.get("view") or "Summary by Item"
    if view == "Reservation Detail (WO -> SO)":
        return _reservation_detail(filters)
    if view == "Incoming Pipeline Detail":
        return _pipeline_detail(filters)
    return _summary(filters)


# --------------------------------------------------------------------------- #
#  Shared helpers                                                             #
# --------------------------------------------------------------------------- #
def _warehouse_list(filters):
    """Resolve the warehouse filter to a concrete list of leaf warehouses. A group
    warehouse expands to all its descendants; blank means 'all warehouses'."""
    wh = filters.get("warehouse")
    if not wh:
        return None  # all
    is_group, lft, rgt = frappe.db.get_value("Warehouse", wh, ["is_group", "lft", "rgt"])
    if not is_group:
        return [wh]
    return [w.name for w in frappe.get_all(
        "Warehouse", filters={"lft": [">=", lft], "rgt": ["<=", rgt], "is_group": 0}, fields=["name"])]


def _item_meta(item_codes):
    if not item_codes:
        return {}
    rows = frappe.get_all("Item", filters={"name": ["in", list(item_codes)]},
                          fields=["name", "item_name", "item_group", "stock_uom"])
    return {r.name: r for r in rows}


def _customer_of(sales_order, _cache={}):
    if not sales_order:
        return None
    if sales_order not in _cache:
        _cache[sales_order] = frappe.db.get_value("Sales Order", sales_order, "customer")
    return _cache[sales_order]


def _so_item_set(sales_order):
    """The raw materials that BELONG to a Sales Order: the components of its FG
    items' default BOMs (single level — matching how Planning consumes stocked
    sub-assemblies) PLUS any components on Work Orders raised for that SO. Used to
    scope the Summary / Pipeline views so a SO filter shows only that order's RM."""
    items = set()
    so = frappe.get_doc("Sales Order", sales_order)
    for it in so.items:
        bom = frappe.db.get_value("Item", it.item_code, "default_bom")
        if bom:
            for c in frappe.get_all("BOM Item", filters={"parent": bom}, fields=["item_code"]):
                items.add(c.item_code)
    for r in frappe.db.sql("""
        SELECT DISTINCT woi.item_code FROM `tabWork Order Item` woi
        JOIN `tabWork Order` wo ON wo.name = woi.parent
        WHERE wo.sales_order = %s""", sales_order, as_dict=True):
        items.add(r.item_code)
    return items


# --------------------------------------------------------------------------- #
#  View 1 — Summary by Item                                                   #
# --------------------------------------------------------------------------- #
def _summary(filters):
    columns = [
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
        {"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 170},
        {"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 120},
        {"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 60},
        {"label": _("On Hand"), "fieldname": "on_hand", "fieldtype": "Float", "width": 90},
        {"label": _("Committed to WOs"), "fieldname": "committed_wo", "fieldtype": "Float", "width": 130},
        {"label": _("Reserved (SRE)"), "fieldname": "reserved_sre", "fieldtype": "Float", "width": 110},
        {"label": _("Free Stock"), "fieldname": "available", "fieldtype": "Float", "width": 90},
        {"label": _("Pending PO"), "fieldname": "pending_po", "fieldtype": "Float", "width": 95},
        {"label": _("Indent Bal."), "fieldname": "indent_balance", "fieldtype": "Float", "width": 95},
        {"label": _("Pending PDI"), "fieldname": "pending_pdi", "fieldtype": "Float", "width": 95},
        {"label": _("In Transit"), "fieldname": "in_transit", "fieldtype": "Float", "width": 90},
        {"label": _("Pending IQC"), "fieldname": "pending_iqc", "fieldtype": "Float", "width": 95},
        {"label": _("Total Incoming"), "fieldname": "total_incoming", "fieldtype": "Float", "width": 110},
        {"label": _("Projected Surplus"), "fieldname": "projected", "fieldtype": "Float", "width": 120},
        {"label": _("Shortfall to Order"), "fieldname": "shortfall", "fieldtype": "Float", "width": 130},
    ]

    item_codes = _candidate_items(filters)
    meta = _item_meta(item_codes)
    stock = _stock_map(filters, item_codes)

    data = []
    tot_short = tot_committed = tot_onhand = 0.0
    n_short = 0
    for code in sorted(item_codes):
        m = meta.get(code)
        if not m:
            continue
        s = stock.get(code, {})
        on_hand = flt(s.get("on_hand"))
        committed = flt(s.get("committed"))
        reserved = flt(s.get("reserved"))
        # raw (signed) balance drives the math; only positive figures are shown.
        raw_available = on_hand - committed - reserved
        available = max(0.0, raw_available)          # Free Stock — never negative

        open_po = _open_po(code)
        p = _pending_pdi(code)
        t = _in_transit(code)
        r = _pending_iqc(code)
        pending_po = max(0.0, open_po - (p + t + r))
        indent_bal = _indent_balance(code)
        incoming = pending_po + indent_bal + p + t + r
        projected_raw = raw_available + incoming
        projected = max(0.0, projected_raw)          # Projected Surplus — never negative
        shortfall = max(0.0, -projected_raw)         # what must still be ordered

        active = any([on_hand, committed, reserved, incoming])
        if filters.get("only_shortfall") and shortfall <= 0:
            continue
        if not filters.get("include_zero") and not active:
            continue

        data.append({
            "item_code": code, "item_name": m.item_name, "item_group": m.item_group,
            "uom": m.stock_uom, "on_hand": on_hand, "committed_wo": committed,
            "reserved_sre": reserved, "available": available, "pending_po": pending_po,
            "indent_balance": indent_bal, "pending_pdi": p, "in_transit": t,
            "pending_iqc": r, "total_incoming": incoming, "projected": projected,
            "shortfall": shortfall,
        })
        tot_short += shortfall
        tot_committed += committed
        tot_onhand += on_hand
        if shortfall > 0:
            n_short += 1

    report_summary = [
        {"label": _("Items Tracked"), "value": len(data), "indicator": "Blue"},
        {"label": _("Items Short"), "value": n_short, "indicator": "Red" if n_short else "Green"},
        {"label": _("Total Shortfall Qty"), "value": flt(tot_short, 2), "indicator": "Red" if tot_short else "Green"},
        {"label": _("Total Committed to WOs"), "value": flt(tot_committed, 2), "indicator": "Orange"},
        {"label": _("Total On Hand"), "value": flt(tot_onhand, 2), "indicator": "Green"},
    ]
    return columns, data, None, None, report_summary, False


def _candidate_items(filters):
    """Every item visible 'from everywhere' — anything with stock, a reservation, or
    a live position anywhere in the inbound pipeline — then narrowed by the item /
    item-group filters. Returns a set of item_codes that are stock items."""
    codes = set()

    # stock / reservation (respecting the warehouse filter)
    wh_list = _warehouse_list(filters)
    bin_cond = "(actual_qty != 0 OR reserved_qty_for_production != 0 OR reserved_qty != 0)"
    params = {}
    if wh_list is not None:
        bin_cond += " AND warehouse IN %(whs)s"
        params["whs"] = tuple(wh_list) or ("",)
    for r in frappe.db.sql(f"SELECT DISTINCT item_code FROM `tabBin` WHERE {bin_cond}", params, as_dict=True):
        codes.add(r.item_code)

    # inbound pipeline sources (so incoming-only items show even at zero stock)
    pipeline_sqls = [
        "SELECT DISTINCT poi.item_code FROM `tabPurchase Order Item` poi JOIN `tabPurchase Order` po ON po.name=poi.parent WHERE po.docstatus=1 AND po.status!='Closed' AND poi.qty>poi.received_qty",
        "SELECT DISTINCT i.item_code FROM `tabIndent Item` i JOIN `tabIndent` p ON p.name=i.parent WHERE p.docstatus=1 AND COALESCE(p.workflow_state,'')!='Ordered'",
        "SELECT DISTINCT i.item_code FROM `tabVendor PDI Item` i JOIN `tabVendor PDI` p ON p.name=i.parent WHERE p.docstatus<2",
        "SELECT DISTINCT i.item_code FROM `tabInbound Logistics Item` i JOIN `tabInbound Logistics` l ON l.name=i.parent WHERE l.docstatus<2",
        "SELECT DISTINCT i.item_code FROM `tabIQC Item` i JOIN `tabIQC` q ON q.name=i.parent WHERE q.docstatus<2",
    ]
    for sql in pipeline_sqls:
        try:
            for r in frappe.db.sql(sql, as_dict=True):
                codes.add(r.item_code)
        except Exception:
            pass  # a pipeline doctype may be absent on some sites — never break the report

    if not codes:
        return set()

    # narrow to stock items in the raw-material groups (always-on), then honour the
    # item / item-group filters (item_group can only narrow further within RM)
    groups = _effective_rm_groups(filters)
    if not groups:
        return set()
    cond = {"name": ["in", list(codes)], "is_stock_item": 1, "item_group": ["in", groups]}
    if filters.get("item_code"):
        cond["name"] = filters["item_code"]
    result = {r.name for r in frappe.get_all("Item", filters=cond, fields=["name"])}

    # scope to a single Sales Order's raw materials when that filter is set
    if filters.get("sales_order"):
        result &= _so_item_set(filters["sales_order"])
    return result


def _stock_map(filters, item_codes):
    """Sum on-hand / committed-to-production / SRE-reserved per item across the
    selected warehouses (all warehouses by default — fixes the single-store gap)."""
    if not item_codes:
        return {}
    params = {"items": tuple(item_codes)}
    cond = "item_code IN %(items)s"
    wh_list = _warehouse_list(filters)
    if wh_list is not None:
        cond += " AND warehouse IN %(whs)s"
        params["whs"] = tuple(wh_list) or ("",)
    rows = frappe.db.sql(f"""
        SELECT item_code,
               SUM(actual_qty) AS on_hand,
               SUM(reserved_qty_for_production) AS committed,
               SUM(reserved_qty) AS reserved
        FROM `tabBin` WHERE {cond} GROUP BY item_code""", params, as_dict=True)
    return {r.item_code: r for r in rows}


# --------------------------------------------------------------------------- #
#  View 2 — Reservation Detail (Work Order -> Sales Order)                    #
# --------------------------------------------------------------------------- #
def _reservation_detail(filters):
    columns = [
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
        {"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 160},
        {"label": _("Source WH"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 120},
        {"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 150},
        {"label": _("WO Status"), "fieldname": "wo_status", "fieldtype": "Data", "width": 100},
        {"label": _("FG Item"), "fieldname": "production_item", "fieldtype": "Link", "options": "Item", "width": 150},
        {"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 140},
        {"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
        {"label": _("Required"), "fieldname": "required_qty", "fieldtype": "Float", "width": 90},
        {"label": _("Transferred"), "fieldname": "transferred_qty", "fieldtype": "Float", "width": 100},
        {"label": _("Consumed"), "fieldname": "consumed_qty", "fieldtype": "Float", "width": 90},
        {"label": _("Still Committed"), "fieldname": "still_committed", "fieldtype": "Float", "width": 120},
    ]

    cond = ["wo.docstatus = 1"]
    params = {}
    if not filters.get("include_completed"):
        cond.append("wo.status NOT IN %(closed)s")
        params["closed"] = CLOSED_WO
    if filters.get("company"):
        cond.append("wo.company = %(company)s"); params["company"] = filters["company"]
    if filters.get("item_code"):
        cond.append("woi.item_code = %(item)s"); params["item"] = filters["item_code"]
    # always-on raw-material scope (item_group narrows within RM only)
    cond.append("woi.item_code IN (SELECT name FROM `tabItem` WHERE item_group IN %(rm_groups)s)")
    params["rm_groups"] = tuple(_effective_rm_groups(filters)) or ("",)
    if filters.get("sales_order"):
        cond.append("wo.sales_order = %(so)s"); params["so"] = filters["sales_order"]
    if filters.get("work_order"):
        cond.append("wo.name = %(wo)s"); params["wo"] = filters["work_order"]

    rows = frappe.db.sql(f"""
        SELECT woi.item_code, wo.source_warehouse AS warehouse, wo.name AS work_order,
               wo.status AS wo_status, wo.production_item, wo.sales_order,
               woi.required_qty, woi.transferred_qty, woi.consumed_qty
        FROM `tabWork Order Item` woi
        JOIN `tabWork Order` wo ON wo.name = woi.parent
        WHERE {' AND '.join(cond)}
        ORDER BY woi.item_code, wo.creation DESC
    """, params, as_dict=True)

    names = {r.item_code for r in rows}
    meta = _item_meta(names)
    data = []
    for r in rows:
        still = flt(r.required_qty) - flt(r.consumed_qty)
        data.append({
            "item_code": r.item_code,
            "item_name": (meta.get(r.item_code) or {}).get("item_name"),
            "warehouse": r.warehouse, "work_order": r.work_order, "wo_status": r.wo_status,
            "production_item": r.production_item, "sales_order": r.sales_order,
            "customer": _customer_of(r.sales_order),
            "required_qty": flt(r.required_qty), "transferred_qty": flt(r.transferred_qty),
            "consumed_qty": flt(r.consumed_qty), "still_committed": still,
        })
    return columns, data, None, None, None, False


# --------------------------------------------------------------------------- #
#  View 3 — Incoming Pipeline Detail                                          #
# --------------------------------------------------------------------------- #
def _pipeline_detail(filters):
    columns = [
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
        {"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 160},
        {"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 120},
        {"label": _("Document"), "fieldname": "document", "fieldtype": "Dynamic Link", "options": "doctype", "width": 170},
        {"label": _("DocType"), "fieldname": "doctype", "fieldtype": "Data", "width": 130},
        {"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
        {"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 150},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
        {"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 140},
    ]

    item = filters.get("item_code")
    rm_groups = set(_effective_rm_groups(filters))  # always-on raw-material scope
    so = filters.get("sales_order")
    so_items = _so_item_set(so) if so else None  # scope pipeline to this SO's RM

    def _ok(code):
        if item and code != item:
            return False
        if frappe.db.get_value("Item", code, "item_group") not in rm_groups:
            return False
        if so_items is not None and code not in so_items:
            return False
        return True

    rows = []

    # --- Indent (submitted, not yet Ordered) ---
    for r in frappe.db.sql("""
        SELECT i.item_code, i.qty, p.name AS doc, p.indent_date AS date,
               COALESCE(p.workflow_state,'Pending') AS status, p.source_sales_order AS so
        FROM `tabIndent Item` i JOIN `tabIndent` p ON p.name=i.parent
        WHERE p.docstatus=1 AND COALESCE(p.workflow_state,'')!='Ordered'""", as_dict=True):
        if _ok(r.item_code):
            rows.append(("Indent", "Indent", r))

    # --- Pending PO (open, not received) ---
    for r in frappe.db.sql("""
        SELECT poi.item_code, (poi.qty - poi.received_qty) AS qty, po.name AS doc,
               po.transaction_date AS date, po.status, po.supplier, NULL AS so
        FROM `tabPurchase Order Item` poi JOIN `tabPurchase Order` po ON po.name=poi.parent
        WHERE po.docstatus=1 AND po.status!='Closed' AND poi.qty>poi.received_qty""", as_dict=True):
        if _ok(r.item_code):
            rows.append(("Pending PO", "Purchase Order", r))

    # --- Vendor PDI (approved, not yet handed to logistics) ---
    for r in frappe.db.sql("""
        SELECT i.item_code, i.approved_qty AS qty, p.name AS doc, p.creation AS date,
               COALESCE(p.status,'At Vendor PDI') AS status, p.purchase_order
        FROM `tabVendor PDI Item` i JOIN `tabVendor PDI` p ON p.name=i.parent
        WHERE p.docstatus<2 AND NOT EXISTS (
            SELECT 1 FROM `tabInbound Logistics` l WHERE l.vendor_pdi=p.name AND l.docstatus<2)""", as_dict=True):
        if _ok(r.item_code):
            r.supplier = frappe.db.get_value("Purchase Order", r.purchase_order, "supplier") if r.purchase_order else None
            rows.append(("Vendor PDI", "Vendor PDI", r))

    # --- In Transit (logistics dispatched / in transit, no IQC yet) ---
    for r in frappe.db.sql("""
        SELECT i.item_code, i.qty, l.name AS doc, l.creation AS date,
               COALESCE(l.status,'In Transit') AS status
        FROM `tabInbound Logistics Item` i JOIN `tabInbound Logistics` l ON l.name=i.parent
        WHERE l.docstatus<2 AND COALESCE(l.status,'') IN ('Dispatched','In Transit')
          AND NOT EXISTS (SELECT 1 FROM `tabIQC` q WHERE q.inbound_logistics=l.name AND q.docstatus<2)""", as_dict=True):
        if _ok(r.item_code):
            rows.append(("In Transit", "Inbound Logistics", r))

    # --- Pending IQC: reached warehouse w/o IQC, plus IQC accepted not GRN'd ---
    for r in frappe.db.sql("""
        SELECT i.item_code, i.qty, l.name AS doc, l.creation AS date, 'Reached Warehouse' AS status
        FROM `tabInbound Logistics Item` i JOIN `tabInbound Logistics` l ON l.name=i.parent
        WHERE l.docstatus<2 AND COALESCE(l.status,'')='Reached Warehouse'
          AND NOT EXISTS (SELECT 1 FROM `tabIQC` q WHERE q.inbound_logistics=l.name AND q.docstatus<2)""", as_dict=True):
        if _ok(r.item_code):
            rows.append(("Pending IQC", "Inbound Logistics", r))
    for r in frappe.db.sql("""
        SELECT i.item_code, i.accepted_qty AS qty, q.name AS doc, q.creation AS date,
               COALESCE(q.status,'IQC Passed') AS status
        FROM `tabIQC Item` i JOIN `tabIQC` q ON q.name=i.parent
        WHERE q.docstatus<2 AND COALESCE(q.status,'')!='Moved to RM'""", as_dict=True):
        if _ok(r.item_code):
            rows.append(("Pending IQC", "IQC", r))

    names = {r[2].item_code for r in rows}
    meta = _item_meta(names)
    data = []
    for stage, doctype, r in rows:
        if flt(r.get("qty")) == 0:
            continue
        data.append({
            "item_code": r.item_code,
            "item_name": (meta.get(r.item_code) or {}).get("item_name"),
            "stage": stage, "document": r.doc, "doctype": doctype, "qty": flt(r.get("qty")),
            "date": (r.get("date").date() if hasattr(r.get("date"), "date") else r.get("date")),
            "supplier": r.get("supplier"), "status": r.get("status"),
            "sales_order": r.get("so"),
        })
    # order: by item, then pipeline stage
    order = {"Indent": 0, "Pending PO": 1, "Vendor PDI": 2, "In Transit": 3, "Pending IQC": 4}
    data.sort(key=lambda d: (d["item_code"], order.get(d["stage"], 9)))
    return columns, data, None, None, None, False
