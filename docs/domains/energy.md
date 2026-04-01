# Energy Domain Guide

> **Scope**: Power generation, dispatch, maintenance, and fuel-constrained scheduling across thermal and renewable assets.

<details><summary>🇷🇺 Краткое описание</summary>

В энергетике Syn-APS моделирует не только производственные операции, но и окна нагрузки, техобслуживание и сетевые ограничения. Setup здесь означает запуск, останов, топливный или режимный переход, а вспомогательные ресурсы включают операторов, резерв мощности и сетевые лимиты.
</details>

---

## 1. Domain Frame

Jobs are dispatch blocks, outage windows, maintenance tasks, fuel transfer tasks, or reserve commitments. Work centers include turbines, boilers, batteries, substations, microgrid assets, and field-service teams.

## 2. SDST Mapping

| Canonical setup concept | Energy realization |
|-------------------------|--------------------|
| State-to-state change | Unit startup, shutdown, ramp, fuel switch |
| Setup time | Warm-up, synchronization, purge, dispatch authorization |
| Material loss | Fuel waste, curtailment, imbalance penalties |
| Energy penalty | Start cost, reserve activation, inefficient ramping |

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Asset is available and synchronized-ready |
| `processing` | Asset is generating, charging, or discharging |
| `setup` | Starting, ramping, or switching operating mode |
| `maintenance` | Planned outage or inspection window |
| `blocked` | Waiting for fuel, permit, network clearance, or crew |

## 4. Setup Matrix Semantics

The setup matrix typically depends on:

- hot, warm, or cold start condition
- fuel type and emissions mode
- target output band
- unit commitment history
- weather and demand forecast regime

## 5. Auxiliary Resources

- field crews and control-room operators
- fuel inventory and transport slots
- spinning reserve and reserve commitments
- transmission corridor capacity
- maintenance permits and inspection teams

## 6. KPI Palette

- dispatch adherence
- start cost and fuel efficiency
- emissions per MWh
- forced outage rate
- reserve coverage
- penalty cost from imbalance or curtailment

## 7. Compliance and Regulatory Context

Common governance surfaces:

- grid-code obligations
- emissions and environmental reporting
- asset safety regulations
- market operator settlement rules

## 8. Example Parametrization

Suggested `domain_attributes` fields:

- `fuel_type`
- `startup_class`
- `ramp_rate_mw_per_min`
- `emission_factor`
- `grid_zone`
- `reserve_commitment_mw`
