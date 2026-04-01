# Metallurgy Domain Guide

> **Scope**: Steel, non-ferrous, casting, rolling, and heat-treatment operations modeled through the Syn-APS canonical kernel.

<details><summary>🇷🇺 Краткое описание</summary>

Металлургия хорошо ложится на каноническую модель Syn-APS: операции связаны тепловой инерцией, сменой марок сплава, общими кранами, ковшами и печами. Главный SDST-драйвер здесь не цвет или SKU, а переход между марками, температурными режимами и состояниями футеровки.
</details>

---

## 1. Domain Frame

Typical jobs are heats, rolling campaigns, casting sequences, or customer orders bundled by alloy and section profile. Work centers include furnaces, ladle-treatment stations, casters, rolling mills, heat-treatment lines, and finishing cells.

## 2. SDST Mapping

In metallurgy, setup means a physical transition between metallurgical states:

| Canonical setup concept | Metallurgy realization |
|-------------------------|------------------------|
| State-to-state change | Alloy grade change, temperature window shift, mold change |
| Setup time | Furnace purge, thermal stabilization, mold swap, roller calibration |
| Material loss | Cropping, purge metal, slag discard, off-spec transition tonnage |
| Energy penalty | Reheating, holding energy, restart energy |

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Work center is available and thermally stable |
| `processing` | Heat, cast, roll, or treat cycle is active |
| `setup` | Grade or tool transition is in progress |
| `maintenance` | Planned refractory, roller, or electrical maintenance |
| `blocked` | Waiting for crane, ladle, mold, inspection, or downstream release |

## 4. Setup Matrix Semantics

The SDST matrix is usually driven by:

- alloy family and impurity constraints
- casting width or profile family
- furnace or ladle refractory condition
- thermal ramp and cooldown requirements
- mold, roll, or die family changes

High-penalty transitions often happen when a premium alloy follows a low-grade or contaminated campaign. Those transitions carry both time and scrap penalties and should be strongly represented in `setup_minutes`, `material_loss`, and `energy_kwh`.

## 5. Auxiliary Resources

Typical auxiliary resources:

- overhead cranes
- ladles and tundishes
- molds and roller sets
- metallurgy crews and inspectors
- gas, oxygen, and cooling utility slots

These resources should be modeled as shared pools with finite capacity rather than embedded directly into machine capacity.

## 6. KPI Palette

Recommended KPI emphasis:

- makespan and campaign completion time
- tardiness for high-value customer orders
- transition scrap tonnes
- energy cost under time-of-day tariffs
- furnace utilization and crane contention
- OEE recovery after unplanned stoppages

## 7. Compliance and Regulatory Context

Common governance surfaces:

- ISO 9001 quality management
- ISO 14001 environmental controls
- IATF 16949 when serving automotive supply chains
- batch genealogy and heat traceability requirements

## 8. Example Parametrization

Reference schema example: [metallurgy.json](../../schema/examples/metallurgy.json)

Suggested `domain_attributes` fields:

- `alloy_grade`
- `heat_number`
- `temperature_celsius`
- `furnace_type`
- `capacity_tonnes`
- `requires_furnace_purge`
