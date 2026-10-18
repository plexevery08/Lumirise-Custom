# Lumirise costing system

`lumirise_custom.costing` is the only authoritative Item/BOM calculator. The
older Item/BOM Client Scripts and Server Scripts are disabled on migration but
kept in the database and cloud-reference export for audit.

## Cost-source precedence

For each raw-material BOM row, the engine resolves a per-unit company-currency
rate in this order:

1. Latest effective, submitted **RM Price Book** containing the item. Within
   that revision: matching quantity range, then preferred vendor, then lowest
   `base_rate`.
2. **Landed import cost**: `RMB price × effective RMB→INR rate`, plus duty.
   The enforced global Sales Platform Settings rate wins by default. Global
   enforcement can be turned off to allow item-specific overrides.
3. **Last Purchase Receipt cost**, captured as a fallback.
4. ERPNext **Item valuation rate**, used only as the final fallback.

The resolved value is displayed on Item as `Commercial Costing Rate`, together
with its source and reference. It is intentionally separate from inventory
valuation. `Copy Commercial Cost to ERP Valuation Rate` is an opt-in
compatibility setting.

## Formula

All monetary steps use commercial half-up rounding at three decimals.

```text
Item price INR       = RMB price × effective RMB→INR rate
Duty                 = Item price INR × duty % / 100
Landed import cost   = Item price INR + Duty

BOM row amount       = component quantity × resolved unit rate
Raw batch total      = Σ BOM row amounts
Raw unit total       = Raw batch total / BOM output quantity

Sub BOM unit cost    = Raw unit total + conversion cost per unit

Parent starting base = Raw unit total
                     + inward transport per unit
                     + factory overhead per unit

Each compound layer  = current base × layer % / 100
Next base             = current base + layer value

Parent BOM unit cost = total after the final marketing layer
MOQ price             = Parent BOM unit cost × (1 + MOQ % / 100)
```

Compound layers run in this fixed business order: dollar fluctuation, interest,
miscellaneous, replacement, and marketing.

`Unit Roll-up Cost` always holds the per-unit value a parent should consume,
whether the child is a Sub BOM or Parent BOM. BOM Item amounts remain batch
amounts for normal ERPNext behavior.

Every BOM also receives a `Costing Status`. A BOM with any zero/unresolved row
is marked `Missing Costs` and is not offered to downstream quotation pricing.

## Automation

- Saving an Item refreshes its derived import fields and cost snapshot.
- Approving or cancelling an RM Price Book refreshes affected Items and BOMs.
- Submitting a Purchase Receipt records the latest actual receipt cost fallback.
- Saving/submitting a BOM recalculates it and cascades through explicit `bom_no`
  links and item-only parent links.
- Changing global costing settings queues a full child-first rebuild.
- The Settings form also has **Rebuild All Costing** for System Managers.

The Item and BOM form previews call the same Python engine; JavaScript contains
no duplicate formula.
