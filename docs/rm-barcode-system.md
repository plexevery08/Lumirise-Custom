# Lumirise RM barcode system

## What the barcode represents

The supplier may send material without a barcode. At Lumirise unloading, one `RM Receiving
Package` is created for each physical carton, pallet, drum, bag or crate. Its `RMPKG-YYYY-#####`
Code 128 label is the permanent Lumirise LPN. It is not an Item barcode and must never be reused.

ERPNext remains the accounting truth:

- Batch identifies the material lot.
- Purchase Receipt (GRN) owns the inward stock transaction.
- Warehouse/Bin identifies the rack balance.
- Stock Entry owns every put-away, transfer and issue.
- RM Receiving Package ties those records to the physical package and scan history.

## End-to-end operating flow

1. Security records the vehicle and Inward Manager approval outside/inside ERP as applicable.
2. Inward collects invoice, packing list, waybill and supporting documents.
3. Purchase Order → Vendor PDI → submitted Inbound Logistics records the consignment.
4. Logistics marks `Reached Warehouse`. ERP creates a Quality handoff task.
5. At Stock-In/unloading, Inward opens Inbound Logistics → Barcode → Generate RM Package Labels.
   Enter item, physical package count, total quantity in the Item's Stock UOM, supplier lot and dates. ERP creates the Batch
   and one LPN per package. Print and attach labels immediately.
6. Inward creates IQC. The inspector uses Barcode → Scan Package Result for every package. The sum
   of accepted and rejected must equal the label quantity. A partially rejected carton is split into
   a new rejection LPN so accepted and rejected stock never share one physical identity. When an IQC
   sample is taken, scan its source package; ERP creates a sample child LPN when needed, which later
   follows the GRN stock into the IQC Lab and through return/consumption/scrap disposition.
7. Submit IQC. A fully rejected IQC cannot create a GRN. A partial rejection creates the Purchase
   defect/claim task already used by the app.
8. Create GRN from IQC. ERP groups GRN rows by Batch and records the exact LPN list on each row.
   Accepted stock lands in Receiving/Staging; rejected stock lands in the configured rejection store.
9. Stores scans the package label, then the rack/location label. ERP validates leaf warehouse,
   status, item-group restriction and optional capacity, and submits an `RM Package Put Away`
   Material Transfer. The package now shows its exact rack.
10. Production submits Material Request. Stores creates the native Pick List and Stock Entry.
11. In the draft `Material Issue to Shop Floor`, Stores scans each LPN. ERP fills the package and
    Batch on the matching row and splits an aggregated pick row when one package is smaller than the
    requested quantity.
12. If the requested quantity is smaller than the scanned carton balance, ERP creates and prints a
    child LPN for the picked quantity; the original label stays on the rack remainder. This guarantees
    one barcode is never shown in two locations. Submit Stock Entry: ERPNext deducts the rack Bin and
    adds the shop-floor Bin, and the picked child/full-package LPN moves to `Issued to Shop Floor`.
    The same LPN can be scanned on line transfers and Manufacture/Consumption entries; it closes as
    `Consumed` only when its traceable quantity is actually consumed.
13. Cancelling GRN, put-away or issue reverses package state and marks the corresponding scan-history
    record as reversed. Normal ERPNext cancellation reverses the Stock Ledger Entries.

Material Request does not deduct stock; that remains standard ERPNext behavior. The submitted Stock
Entry created from the Pick List is the auditable deduction point.

## Logins and responsibilities

| Login/persona | Required roles | Barcode responsibility |
|---|---|---|
| Inward Executive/Manager | Lumirise Operations, Purchase User | Mark arrival, generate labels, attach them, create IQC/GRN drafts |
| IQC Inspector | Lumirise Operations, Quality User | Scan every package and record accepted/rejected quantity |
| Quality Manager | Quality Manager | Submit IQC and control rejection disposition |
| RM Stores Executive | Lumirise Operations, Stock User | Scan package + rack for put-away and package during picking |
| RM Stores Manager | Factory Store Manager, Stock Manager | Submit/cancel stock moves, capacity/rack control, reconciliation |
| Purchase | Purchase User/Manager | PO, container release, GRN/rejection claim oversight |
| System Manager | System Manager | Configure fields, printers, roles and staged enforcement |

Assign actual users in `Lumirise Department Map` for `Quality - PDI/IQC` and `Stores - RM` so ERP
tasks and escalation reach named owners. Do not share accounts; every scan stores `frappe.session.user`.

## Configuration

In Lumirise Operations Settings configure:

- Raw Material Store: the parent/group containing all RM rack warehouses.
- Receiving / Staging: a separate leaf warehouse for accepted GRN stock awaiting put-away.
- Rejection Store.
- Enable RM Barcode System = on.
- Require Batch for RM Packages = on.
- Enforce RM Package Scan = off during migration, on only after UAT/opening-stock labelling.

For every rack/bay leaf Warehouse set a unique Location Barcode. Capacity is optional. Capacity is
only numerically enforceable when stock in that slot uses a compatible quantity basis; mixed UOM
slots should leave capacity zero and use physical package/pallet limits operationally.

For each RM Item that will be enforced, enable ERPNext `Has Batch No` and `Track RM Packages`.

## Printer and mobile infrastructure

- Thermal label printer capable of 100 mm × 50 mm labels (the supplied format is 98 mm × 48 mm).
- Labels/ribbon suitable for the material environment.
- Any desktop or mobile browser logged into ERPNext can scan with a Bluetooth/USB scanner acting as
  a keyboard. Android handhelds are recommended for continuous shop use.
- The shipped format produces Code 128 in ERP/PDF/browser printing. Direct ZPL/TSPL silent printing
  needs a local print bridge and is deliberately separate from stock logic.
- Keep a normal keyboard/manual-entry fallback; server validation is the same for both.

## Deployment (test site first)

```bash
bench --site TEST_SITE backup --with-files
bench get-app --branch agent/rm-barcode-system REPOSITORY_URL  # only if app is not present
bench setup requirements
bench --site TEST_SITE migrate
bench build --app lumirise_custom
bench --site TEST_SITE clear-cache
bench --site TEST_SITE run-tests --app lumirise_custom --doctype "RM Receiving Package"
```

Then configure warehouses/items and run the UAT below. Deploy to production only after the test-site
result is signed off. Migrate first with enforcement off; never switch it on during an open shift.

## Opening-stock migration

1. Freeze RM movements for a count window.
2. Export current Item × Batch × Warehouse balances.
3. Physically count and split each balance into actual cartons/pallets.
4. Open the RM Receiving Package list → Create Opening Stock Labels. Select Item, rack, existing
   Batch, physical package count, total counted quantity and the reconciliation reference; print labels.
5. Attach labels, scan-audit every rack, and reconcile differences with an approved Stock
   Reconciliation (never by editing package quantities alone).
6. Confirm the health check reports zero unlabelled tracked balances.
7. Enable `Enforce RM Package Scan` for a controlled shift, then permanently after sign-off.

## Minimum UAT

- Full accepted import: 3 cartons → labels → IQC → GRN → three different racks.
- Partial rejection: one carton split into accepted and rejected labels; verify both GRN warehouses.
- Capacity/block test: put-away to full, blocked, group and wrong-item-group locations must fail.
- Material Request for more than one package: Pick List → scan multiple LPNs → submit issue; verify rack
  Bins, shop-floor Bin and package remaining quantities.
- Partial issue and full issue.
- Wrong item, wrong Batch, wrong source rack, duplicate location barcode and over-issue must fail.
- Purchase-UOM conversion: receive an item whose PO UOM differs from Stock UOM; confirm the package,
  IQC, GRN and Stock Entry quantities reconcile exactly.
- API bypass: manual package insertion, a hand-built put-away to a non-RM warehouse, moving rejected
  material, and submitting a tracked GRN without the linked IQC/package list must fail.
- Cancel issue, put-away and GRN in reverse dependency order; verify ledger and package restoration.
- Print ten labels and scan each from paper using the actual mobile/scanner and production printer.
- Permissions: Inward cannot submit stock moves; Stores cannot submit IQC; Quality cannot alter racks.

## Rollout controls

The package scan gate is controlled by both Item (`Track RM Packages`) and Operations Settings
(`Enforce RM Package Scan`). This allows a gradual item-group rollout. Never mark an item tracked
until its opening stock is fully represented by active package records.
