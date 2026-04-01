# Food and Beverage Domain Guide

> **Scope**: Process and packaging lines with allergen, flavor, freshness, and sanitation constraints.

<details><summary>🇷🇺 Краткое описание</summary>

Пищевая промышленность особенно чувствительна к SDST: переходы между вкусами, аллергенами, рецептурами и форматами упаковки напрямую влияют на мойку, потери и shelf-life. Syn-APS позволяет формализовать эти переходы так же строго, как в металлургии или фарме.
</details>

---

## 1. Domain Frame

Jobs are batches, packaging runs, recipe campaigns, or shipping-bound freshness windows. Work centers include mixers, cookers, fillers, packaging lines, CIP stations, cold rooms, and palletizing cells.

## 2. SDST Mapping

| Canonical setup concept | Food and beverage realization |
|-------------------------|-------------------------------|
| State-to-state change | Recipe, flavor, allergen, or package format change |
| Setup time | Cleaning, sterilization, label change, filler calibration |
| Material loss | Flush product, spoilage, label waste, off-spec discard |
| Energy penalty | Thermal stabilization, cold-chain recovery, CIP utilities |

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Line is ready and sanitary |
| `processing` | Mixing, cooking, filling, or packaging is active |
| `setup` | Cleaning, flavor change, or format change in progress |
| `blocked` | Waiting for ingredients, QA release, or packaging materials |
| `maintenance` | Planned service or deep sanitation window |

## 4. Setup Matrix Semantics

The matrix typically depends on:

- allergen hierarchy
- flavor strength and carryover risk
- packaging format family
- temperature regime
- shelf-life sensitivity and freshness window

## 5. Auxiliary Resources

- CIP/SIP capacity
- QA release staff
- packaging materials and label sets
- cold-room slots
- sanitation crews

## 6. KPI Palette

- on-time fill rate
- freshness-window compliance
- allergen changeover time
- waste and giveaway
- OEE by line
- sanitation-driven downtime

## 7. Compliance and Regulatory Context

Common controls:

- HACCP
- BRCGS / IFS / FSSC 22000 depending on market
- allergen segregation requirements
- traceability and recall readiness

## 8. Example Parametrization

Reference schema example: [food_beverage.json](../../schema/examples/food_beverage.json)

Suggested `domain_attributes` fields:

- `allergen_class`
- `recipe_family`
- `package_format`
- `shelf_life_hours`
- `cold_chain_required`
- `cip_recipe`
