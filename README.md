# Lumirise Custom

Custom ERPNext **v16** app for **Lumirise** — an LED **OEM** manufacturer in India — built by
**Saphaare Labs**. It layers Lumirise's real order-to-dispatch process on top of standard ERPNext:
landed-cost-driven costing, a sales pricing engine, cross-department task orchestration, line-aware
production, and mandatory quality gates.

App module: `lumirise_custom` · License: MIT.

---

## What's inside

The app wires onto standard ERPNext documents (Item, BOM, Sales Order, Work Order, Purchase Receipt,
Delivery Note, …) via `hooks.py` and adds **29 custom DocTypes**. Nine subsystems:

| # | Subsystem | Code | What it does |
|---|---|---|---|
| 1 | **Costing chain** | `costing.py`, `setup/costing_fields.py` | Item landed cost (RMB→INR+duty) → sub-BOM rollup → parent-BOM layered cost → MOQ slab prices. Auto-recomputes on Item / BOM / GRN / Stock Entry; cascades to parent BOMs. |
| 2 | **Sales Platform pricing engine** | `pricing_engine.py`, `doctype/price_sheet/*`, `queries.py` | Port of the web platform's `pricing.ts`. Price Sheet → approval prices → **real ERPNext Quotation**; mono/master-box + transport + credit-term pricing; daily expiry of pending sheets. |
| 3 | **Task / Kanban orchestration** | `task_engine.py` | Auto-raises handoff / defect / rework cards for the next department on every lifecycle event; daily overdue → HOD escalation. All handlers fail-safe (never block the business doc). |
| 4 | **Sales Order status sync** | `status_sync.py` | Forward-only, fail-safe writes of `lr_planning_status` / `lr_purchase_status` / `lr_production_status` off real events. |
| 5 | **Line-aware production drivers** | `production.py` | One-click Focus-9 helpers (`issue_to_shop_floor`, `transfer_to_line`, `receive_finished_goods`, `reject_from_line`, `move_to_dispatch`) over native Work Orders, with per-line WIP warehouses. |
| 6 | **Stores** | `stores.py` | Native Pick List (WO material issue + delivery) with rack/bin locations, GRN put-away, pick-&-stage tasks. |
| 7 | **Quality gates** | `events.py` | IQC gate blocks Purchase Receipt submit; Customer PDI gate blocks Delivery Note submit. |
| 8 | **Procurement / dispatch flow chain** | `chain.py` | Doc-to-doc mappers: Vendor PDI → Inbound Logistics → IQC → GRN, and Customer PDI → Delivery Note → Sales Invoice. |
| 9 | **Indent + Material Planning (MRP)** | `doctype/indent/*`, `doctype/material_planning/*` | Indent with the `Indent Approval` workflow; Material Planning posts Indents + Work Orders and advances SO status. |

**Foundation**
- **Dynamic config** — `defaults.py` resolves every warehouse / company / UOM / feature flag from the
  single **Lumirise Operations Settings** doc. Nothing operational is hard-coded; a missing setting
  raises a clear, actionable error.
- **Idempotent setup** — `setup/` runs on `after_migrate`: seeds core + line warehouses, stock-entry
  types, backflush mode, roles, credit terms, costing/flow fields, the task engine, and the workspace.
- **Client scripts** — custom buttons on Purchase Order, Sales Order, Work Order (`public/js/`).
- **Fixtures** — custom fields, property setters, the `Indent Approval` workflow, and the workspace
  ship with the app.

> Order-to-cash, end to end:
> Price Sheet → Quotation → Sales Order → Material Planning → Indent → Purchase Order →
> Inbound Logistics → IQC → GRN → (production: issue → transfer → receive → reject/dispatch) →
> Customer PDI → Delivery Note → Sales Invoice.

For the full, code-referenced breakdown (per-event task table, production-driver→screen mapping),
see the audit kept in the companion ERPAios workspace:
`outputs/2026-06-13-custom-app-feature-inventory.md`.

---

## Installation

Install with the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app lumirise_custom
```

On install/migrate, `setup/after_migrate` seeds roles, costing fields, credit terms, and the
production-flow warehouses. Configure the rest in **Lumirise Operations Settings** before running the
flow — engines read warehouses/company/UOM from there.

## Contributing

This app uses `pre-commit` for code formatting and linting. Please
[install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/lumirise_custom
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

**House rules**
- Resolve operational warehouses/company/UOM through `defaults.py` — never hard-code them.
- New cross-document automation belongs in the engine modules and is wired via `hooks.py`
  `doc_events`; keep handlers **fail-safe** so they never block the underlying business document.
- Status only ever advances (see `status_sync.py`); never silently regress it.

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and
  [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.

### License

mit
