# Idempotent demo-master setup for the Lumirise "Focus 9 process-flow" demo.
# Builds a realistic LED-panel world (two panels sharing common parts) so the
# Material Planning cockpit, multi-indent->PO consolidation, and the
# Vendor PDI -> Logistics -> IQC -> GRN chain all demonstrate on camera.
#
# Run:  bench --site site.com execute lumirise_custom.demo.setup_demo.execute
# Safe to re-run: every create is guarded by an exists() check.

import frappe

COMPANY = "Lumirise"
ABBR = "L"
STORES = "Stores - L"

# ---------------------------------------------------------------- item groups
ITEM_GROUPS = ["LED Finished Goods", "LED Sub-Assembly", "LED Raw Material", "LED Packaging"]

# ----------------------------------------------------------------- warehouses
# (Stores, Shopfloor Stock in Area, Finished Goods, Customer PDI, Dispatch,
#  Goods In Transit already exist on the bench.)
NEW_WAREHOUSES = [
    "IQC Hold - L",
    "RM Rejection - L",
    "Line-1 WIP - L",
    "Line-2 WIP - L",
    "Semi-Finished - L",
]

# ----------------------------------------------------------------------- items
# (code, item_group, buying_rate)  -- buying_rate seeds Standard Buying price.
RAW = "LED Raw Material"
PKG = "LED Packaging"
SUB = "LED Sub-Assembly"
FG = "LED Finished Goods"

ITEMS = [
    # finished goods
    ("LED-PANEL-24W", FG, None),
    ("LED-PANEL-36W", FG, None),
    # sub-assembly (has its own BOM)
    ("MCPCB-24W-ASSY", SUB, 60.0),
    # 24W components
    ("HOUSING-24W", RAW, 40.0),
    ("DIFFUSER-24W", RAW, 25.0),
    ("REFLECTOR-24W", RAW, 15.0),
    # 36W components
    ("HOUSING-36W", RAW, 55.0),
    ("DIFFUSER-36W", RAW, 32.0),
    ("REFLECTOR-36W", RAW, 18.0),
    # shared components (these drive the multi-indent consolidation)
    ("WIRE-SET", RAW, 8.0),
    ("SCREW-M3", RAW, 0.5),
    ("DRIVER-24W", RAW, 35.0),       # imported, IQC-required, deliberately short
    # MCPCB sub-assembly components
    ("PCB-RAW", RAW, 12.0),
    ("DRIVER-IC", RAW, 8.0),
    ("RESISTOR", RAW, 0.3),
    ("CAPACITOR", RAW, 0.5),
    # packaging
    ("MONO-BOX-24W", PKG, 6.0),
    ("MASTER-BOX-24W", PKG, 20.0),
    ("MONO-BOX-36W", PKG, 7.0),
    ("MASTER-BOX-36W", PKG, 22.0),
    ("BOPP-TAPE", PKG, 30.0),
    ("STRAPPING", PKG, 10.0),
]

# ------------------------------------------------------------------------ BOMs
# name, fg_item, [(component, qty), ...]
BOM_MCPCB = ("BOM-MCPCB-24W", "MCPCB-24W-ASSY", [
    ("PCB-RAW", 1), ("DRIVER-IC", 1), ("RESISTOR", 4), ("CAPACITOR", 2),
])
# Per-unit production BOM. Mono box is consumed per unit (qty 1). Master box,
# BOPP tape and strapping are carton-level packaging applied at the packing/PDI
# stage, not the per-unit BOM (UOM "Nos" requires whole numbers).
BOM_PANEL_24 = ("BOM-LED-PANEL-24W", "LED-PANEL-24W", [
    ("HOUSING-24W", 1), ("DIFFUSER-24W", 1), ("REFLECTOR-24W", 1),
    ("MCPCB-24W-ASSY", 1), ("DRIVER-24W", 1), ("WIRE-SET", 1),
    ("SCREW-M3", 6), ("MONO-BOX-24W", 1),
])
BOM_PANEL_36 = ("BOM-LED-PANEL-36W", "LED-PANEL-36W", [
    ("HOUSING-36W", 1), ("DIFFUSER-36W", 1), ("REFLECTOR-36W", 1),
    ("MCPCB-24W-ASSY", 1), ("DRIVER-24W", 1), ("WIRE-SET", 1),
    ("SCREW-M3", 8), ("MONO-BOX-36W", 1),
])

# --------------------------------------------------------------------- parties
CUSTOMERS = ["Starlight Electricals", "Bright Lights Distributors"]
SUPPLIERS = [
    "Shenzhen LED Imports",      # import / China  -> DRIVER-24W, MCPCB parts
    "Fastener Supplies Co",      # SCREW-M3
    "Panel Components India",    # housing/diffuser/reflector/wire
    "Packaging India",           # boxes / tape / strapping
]

# item -> default supplier. Lets the multi-indent->PO step group consolidated
# demand by vendor (e.g. all the screws across SOs onto one Fastener PO).
SUPPLIER_MAP = {
    "DRIVER-24W": "Shenzhen LED Imports",
    "PCB-RAW": "Shenzhen LED Imports", "DRIVER-IC": "Shenzhen LED Imports",
    "RESISTOR": "Shenzhen LED Imports", "CAPACITOR": "Shenzhen LED Imports",
    "SCREW-M3": "Fastener Supplies Co",
    "HOUSING-24W": "Panel Components India", "DIFFUSER-24W": "Panel Components India",
    "REFLECTOR-24W": "Panel Components India", "HOUSING-36W": "Panel Components India",
    "DIFFUSER-36W": "Panel Components India", "REFLECTOR-36W": "Panel Components India",
    "WIRE-SET": "Panel Components India",
    "MONO-BOX-24W": "Packaging India", "MASTER-BOX-24W": "Packaging India",
    "MONO-BOX-36W": "Packaging India", "MASTER-BOX-36W": "Packaging India",
    "BOPP-TAPE": "Packaging India", "STRAPPING": "Packaging India",
}

# selling slab pricing (min_qty, max_qty, rate) -- proves "rate fixed by qty slab"
SLABS = {
    "LED-PANEL-24W": [(1, 99, 480), (100, 499, 450), (500, 2999, 430), (3000, 0, 410)],
    "LED-PANEL-36W": [(1, 99, 660), (100, 499, 620), (500, 2999, 595), (3000, 0, 570)],
}

# opening stock in Stores - L. DRIVER-24W + SCREW-M3 deliberately short so
# planning shows a real shortfall and raises indents -> the procurement chain runs.
OPENING_STOCK = {
    "HOUSING-24W": 3000, "DIFFUSER-24W": 3000, "REFLECTOR-24W": 3000,
    "HOUSING-36W": 2000, "DIFFUSER-36W": 2000, "REFLECTOR-36W": 2000,
    "WIRE-SET": 6000, "MCPCB-24W-ASSY": 5000,
    "DRIVER-24W": 2000,        # need 5000 -> 3000 short
    "SCREW-M3": 10000,         # need 34000 -> 24000 short
    "MONO-BOX-24W": 3000, "MASTER-BOX-24W": 200,
    "MONO-BOX-36W": 2000, "MASTER-BOX-36W": 150,
    "BOPP-TAPE": 1000, "STRAPPING": 1000,
    "PCB-RAW": 500, "DRIVER-IC": 500, "RESISTOR": 2000, "CAPACITOR": 1000,
}
OPENING_REMARK = "LUMIRISE_PANEL_OPENING"


def _ensure_item_group(name):
    if not frappe.db.exists("Item Group", name):
        frappe.get_doc({
            "doctype": "Item Group", "item_group_name": name,
            "parent_item_group": "All Item Groups", "is_group": 0,
        }).insert(ignore_permissions=True)


def _ensure_warehouse(name):
    if frappe.db.exists("Warehouse", name):
        return
    wh_name = name.rsplit(" - ", 1)[0]
    frappe.get_doc({
        "doctype": "Warehouse", "warehouse_name": wh_name, "company": COMPANY,
        "parent_warehouse": f"All Warehouses - {ABBR}", "is_group": 0,
    }).insert(ignore_permissions=True)


def _ensure_item(code, group, buying_rate):
    if not frappe.db.exists("Item", code):
        frappe.get_doc({
            "doctype": "Item", "item_code": code, "item_name": code,
            "item_group": group, "stock_uom": "Nos", "is_stock_item": 1,
            "include_item_in_manufacturing": 1,
            "default_warehouse": STORES,
            "gst_hsn_code": "85391000",
        }).insert(ignore_permissions=True)
    if buying_rate is not None:
        _ensure_item_price(code, "Standard Buying", buying_rate, buying=1)
    _ensure_item_default(code)


def _ensure_item_default(code):
    supplier = SUPPLIER_MAP.get(code)
    if not supplier:
        return
    item = frappe.get_doc("Item", code)
    row = next((d for d in item.item_defaults if d.company == COMPANY), None)
    if row and row.default_supplier == supplier:
        return
    if row:
        row.default_supplier = supplier
    else:
        item.append("item_defaults", {"company": COMPANY, "default_supplier": supplier})
    item.save(ignore_permissions=True)


def _ensure_item_price(item_code, price_list, rate, buying=0, selling=0):
    if frappe.db.exists("Item Price", {"item_code": item_code, "price_list": price_list}):
        return
    frappe.get_doc({
        "doctype": "Item Price", "item_code": item_code, "price_list": price_list,
        "buying": buying, "selling": selling, "price_list_rate": rate,
    }).insert(ignore_permissions=True)


def _ensure_bom(name, fg_item, components):
    if frappe.db.exists("BOM", name):
        return
    bom = frappe.get_doc({
        "doctype": "BOM", "item": fg_item, "company": COMPANY,
        "quantity": 1, "is_active": 1, "is_default": 1,
        "rm_cost_as_per": "Price List", "buying_price_list": "Standard Buying",
        "items": [{"item_code": c, "qty": q} for c, q in components],
    })
    bom.insert(ignore_permissions=True)
    # force the human-friendly name
    if bom.name != name:
        frappe.rename_doc("BOM", bom.name, name, force=True)
    bom = frappe.get_doc("BOM", name)
    bom.submit()


def _ensure_customer(name):
    if not frappe.db.exists("Customer", name):
        frappe.get_doc({
            "doctype": "Customer", "customer_name": name,
            "customer_type": "Company", "customer_group": "Commercial",
            "territory": "All Territories",
        }).insert(ignore_permissions=True)


def _ensure_supplier(name):
    if not frappe.db.exists("Supplier", name):
        frappe.get_doc({
            "doctype": "Supplier", "supplier_name": name,
            "supplier_group": "Raw Material", "country": "India",
        }).insert(ignore_permissions=True)


def _ensure_slab_pricing(item_code, slabs):
    for i, (mn, mx, rate) in enumerate(slabs, start=1):
        title = f"{item_code} Slab {i}"
        if frappe.db.exists("Pricing Rule", {"title": title}):
            continue
        frappe.get_doc({
            "doctype": "Pricing Rule", "title": title,
            "apply_on": "Item Code", "selling": 1, "company": COMPANY,
            "price_or_product_discount": "Price",
            "rate_or_discount": "Rate", "rate": rate,
            "min_qty": mn, "max_qty": mx, "priority": str(min(i, 9)),
            "items": [{"item_code": item_code}],
        }).insert(ignore_permissions=True)
    # also a base Standard Selling price (sample / below-slab list rate)
    _ensure_item_price(item_code, "Standard Selling", slabs[0][2], selling=1)


def _ensure_opening_stock():
    if frappe.db.exists("Stock Entry", {"remarks": OPENING_REMARK, "docstatus": 1}):
        return
    se = frappe.get_doc({
        "doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
        "company": COMPANY, "remarks": OPENING_REMARK,
        "items": [
            {"item_code": code, "qty": qty, "t_warehouse": STORES,
             "basic_rate": frappe.db.get_value(
                 "Item Price", {"item_code": code, "price_list": "Standard Buying"},
                 "price_list_rate") or 1.0}
            for code, qty in OPENING_STOCK.items()
        ],
    })
    se.insert(ignore_permissions=True)
    se.submit()


def execute():
    for g in ITEM_GROUPS:
        _ensure_item_group(g)
    for w in NEW_WAREHOUSES:
        _ensure_warehouse(w)
    for code, group, rate in ITEMS:
        _ensure_item(code, group, rate)
    for c in CUSTOMERS:
        _ensure_customer(c)
    for s in SUPPLIERS:
        _ensure_supplier(s)
    for name, fg, comps in (BOM_MCPCB, BOM_PANEL_24, BOM_PANEL_36):
        _ensure_bom(name, fg, comps)
    for item, slabs in SLABS.items():
        _ensure_slab_pricing(item, slabs)
    _ensure_opening_stock()
    frappe.db.commit()
    print("Lumirise panel demo masters ready.")
    print("  FGs:", frappe.get_all("Item", {"item_group": FG}, pluck="name"))
    print("  BOMs:", frappe.get_all("BOM", {"item": ["like", "LED-PANEL%"]}, pluck="name"))
    print("  Stores stock rows:", len(OPENING_STOCK))
