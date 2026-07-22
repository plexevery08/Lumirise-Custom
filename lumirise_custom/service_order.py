# Copyright (c) 2026, riddhi solanki and contributors
# For license information, please see license.txt

# Service Indent -> Service Order (subcontracting) bridge.
#
# Focus 9 flow: Service Indent (rate-less: bare board + RM components, narration =
# the SMT/assembled output) -> Service Order (vendor + rate) -> vendor does the
# job-work, returns SEMI-FINISHED goods.
#
# ERPNext native mapping (v16, confirmed against erpnext source):
#   Service Indent   = Indent (indent_type=Service)                [demand]
#   Service Order    = Subcontracting Order                        [RM supply + FG receipt]
#   priced doc       = Purchase Order (is_subcontracted=1)         [supplier + service rate + fg_item]
# The PO is the head of the native subcontracting flow; the Subcontracting Order is
# created FROM it (subcontracting_order.purchase_order) and pulls the supplied RM from
# the fg_item's DEFAULT BOM (subcontracting_order.py: Subcontracting BOM OR item.default_bom).
#
# So this bridge only has to: resolve the SEMI-FINISHED fg_item from the indent, then
# build a subcontract PO (route, don't insert -- doctype Rule 2). Native takes it from
# there and the existing verified subcontracting chain (lumirise-subcontracting-flow) runs.

import frappe
from frappe.utils import flt, nowdate, add_days

from lumirise_custom import defaults as config

# The generic non-stock job-work charge line put on the subcontract PO. Its rate is
# left 0 here (price deferred -- comes from the Purchase-Level Service Order file once
# the client confirms the mapping); the buyer/native flow fills the rate on the PO.
SERVICE_ITEM_CODE = "SMT-SUBCON-SERVICE"
SERVICE_ITEM_GROUP_FALLBACK = "Services"
# SAC for job-work / subcontracting ("Other manufacturing services n.e.c." under the
# 9988 "manufacturing services on physical inputs owned by others" heading). India
# Compliance makes gst_hsn_code mandatory on Items AND requires a 6- or 8-digit code,
# so the auto-created service item must carry a valid 6-digit SAC or the insert throws.
SERVICE_SAC_CODE = "998877"


def _service_item():
    """Get-or-create the non-stock job-work service item used on the subcontract PO line."""
    if frappe.db.exists("Item", SERVICE_ITEM_CODE):
        return SERVICE_ITEM_CODE
    group = "Services" if frappe.db.exists("Item Group", "Services") else \
        frappe.db.get_value("Item Group", {"is_group": 0}, "name")
    doc = frappe.get_doc({
        "doctype": "Item",
        "item_code": SERVICE_ITEM_CODE,
        "item_name": "SMT Subcontracting Service",
        "description": "Job-work / SMT assembly service charge (subcontracting).",
        "item_group": group,
        "stock_uom": "Nos",
        "is_stock_item": 0,
        "is_purchase_item": 1,
        "is_sub_contracted_item": 0,
    })
    # India Compliance: gst_hsn_code is mandatory on Item. Set a valid SAC when the
    # field exists and the code is present in the GST HSN Code master; otherwise leave
    # it blank and let validation surface (the client then supplies the correct SAC).
    if doc.meta.has_field("gst_hsn_code") and frappe.db.exists("GST HSN Code", SERVICE_SAC_CODE):
        doc.gst_hsn_code = SERVICE_SAC_CODE
    doc.insert(ignore_permissions=True)
    return doc.name


def resolve_fg(indent):
    """Resolve the SEMI-FINISHED output item for a Service Indent from the existing
    normal BOMs (NOT a subcontracting BOM -- Lumirise's BOMs live in the standard BOM
    doctype). Strategy proven against all 55 Apr-Jun service indents (55/55 mapped):

      bare board (indent line 1) -> BOMs that contain it -> the BOM whose components
      best overlap the indent's RM lines -> that BOM's parent item = the semi-finished FG.

    The bare board sits in one BOM per colour/current variant; best RM-overlap picks the
    right variant (the distinguishing LED/part disambiguates). Returns:
        {fg_item, bom, fg_qty, overlap, rm_count, ambiguous}
    or raises if the board is in no BOM.
    `indent` may be an Indent name or doc.
    """
    doc = indent if hasattr(indent, "items") else frappe.get_doc("Indent", indent)
    if not doc.items:
        frappe.throw("This indent has no item lines.")

    rm = {r.item_code for r in doc.items if r.item_code}
    board = doc.items[0].item_code                 # the bare board / driver PCB
    board_qty = flt(doc.items[0].qty)              # 1-per-FG line -> the job qty

    parents = frappe.get_all("BOM Item", filters={"item_code": board}, pluck="parent")
    parents = list(dict.fromkeys(parents))         # de-dupe, keep order
    if not parents:
        frappe.throw(
            f"Cannot resolve a semi-finished item: the bare board <b>{board}</b> is not a "
            f"component of any BOM. Add its BOM, or set the FG item manually.")

    best = None
    for bom in parents:
        meta = frappe.db.get_value("BOM", bom, ["item", "is_active", "is_default"], as_dict=True)
        if not meta:
            continue
        comps = set(frappe.get_all("BOM Item", filters={"parent": bom}, pluck="item_code"))
        score = len(rm & comps)
        key = (score, int(meta.is_active or 0), int(meta.is_default or 0))
        if best is None or key > best[0]:
            best = (key, bom, meta.item, score, len(comps))

    _key, bom, fg, score, ncomp = best
    return {
        "fg_item": fg,
        "bom": bom,
        "fg_qty": board_qty or 1,
        "overlap": score,
        "rm_count": len(rm),
        # flag low-confidence matches for human review (3 of 55 in the source data)
        "ambiguous": score < max(1, len(rm) * 0.6),
    }


@frappe.whitelist()
def make_service_order(indent):
    """Service Indent -> a Draft subcontract Purchase Order (the native 'Service Order').
    Route-don't-insert (Rule 2): opens a fresh, Draft PO for the buyer to complete
    (vendor rate) and then run native 'Create > Subcontracting Order'. Returns the PO name.

    The PO line = the job-work SERVICE item; fg_item = the resolved semi-finished output;
    fg_item_qty = the job qty. Supplied RM is derived natively from fg_item.default_bom at
    the Subcontracting Order stage -- we do NOT copy the indent's RM lines onto the PO.
    """
    frappe.has_permission("Purchase Order", "create", throw=True)
    doc = frappe.get_doc("Indent", indent) if isinstance(indent, str) else indent
    if (doc.get("indent_type") or "Purchase") != "Service":
        frappe.throw("Create Service Order is only for Service-type indents. "
                     "Use Create Purchase Plan for Purchase indents.")

    supplier = doc.get("service_supplier")
    if not supplier:
        frappe.throw("Set the <b>Service Supplier</b> (job-work vendor) on the indent first.")

    res = resolve_fg(doc)
    service_item = _service_item()
    company = config.get_company(doc)

    po = frappe.new_doc("Purchase Order")
    po.supplier = supplier
    po.company = company
    po.transaction_date = nowdate()
    po.schedule_date = add_days(nowdate(), 15)
    po.is_subcontracted = 1
    po.is_old_subcontracting_flow = 0
    po.lr_indent_refs = doc.name          # provenance (Data field already on PO)
    po.append("items", {
        "item_code": service_item,
        "qty": res["fg_qty"],
        "rate": 0,                         # price deferred -- filled on the PO
        "fg_item": res["fg_item"],
        "fg_item_qty": res["fg_qty"],
        "schedule_date": add_days(nowdate(), 15),
    })
    po.insert(ignore_permissions=True)

    # Data back-ref on the indent (Rule 1: string, not a reverse Link).
    if doc.meta.has_field("service_order_ref"):
        frappe.db.set_value("Indent", doc.name, "service_order_ref", po.name)
    if doc.meta.has_field("service_fg_item"):
        frappe.db.set_value("Indent", doc.name, "service_fg_item", res["fg_item"])

    if res["ambiguous"]:
        frappe.msgprint(
            f"Heads-up: the semi-finished item <b>{res['fg_item']}</b> was matched with low "
            f"confidence ({res['overlap']}/{res['rm_count']} components). Please confirm it is "
            f"correct before submitting.", title="Check the semi-finished item", indicator="orange")

    return po.name
