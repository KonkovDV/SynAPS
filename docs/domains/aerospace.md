# Aerospace Domain Guide

> **Scope**: MRO, composite manufacturing, precision assembly, and certified inspection-driven scheduling.

<details><summary>🇷🇺 Краткое описание</summary>

Аэрокосмос сочетает высокую стоимость ошибки, сложную прослеживаемость и жесткие hold points. Здесь setup определяется сменой материалов, инструментов, cleanroom-режимов и NDT-процедур, а auxiliary resources включают сертифицированный персонал, оснастку и инспекционные окна.
</details>

---

## 1. Domain Frame

Jobs are maintenance packages, assembly orders, composite layup campaigns, inspection sequences, or repair directives. Work centers include clean rooms, autoclaves, machining cells, assembly bays, paint booths, and non-destructive testing stations.

## 2. SDST Mapping

| Canonical setup concept | Aerospace realization |
|-------------------------|-----------------------|
| State-to-state change | Material system, part family, or certification route shift |
| Setup time | Tooling swap, autoclave recipe change, cleanroom prep, NDT calibration |
| Material loss | Composite scrap, rework hours, coating purge, expired prepreg |
| Energy penalty | Autoclave cycle energy, environmental control stabilization |

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Certified asset is available |
| `processing` | Fabrication, layup, assembly, or inspection in progress |
| `setup` | Tooling, calibration, or environment reset in progress |
| `blocked` | Waiting for engineering disposition, parts, or inspection sign-off |
| `maintenance` | Planned service, recalibration, or certification renewal |

## 4. Setup Matrix Semantics

The setup matrix is usually driven by:

- material system and cure profile
- tooling family and fixture compatibility
- cleanroom or contamination class
- certification route and inspection sequence
- coating or adhesive family

## 5. Auxiliary Resources

- certified technicians by authorization level
- fixtures and composite tools
- autoclave slots
- NDT inspectors and equipment
- quality and engineering sign-off capacity

## 6. KPI Palette

- schedule adherence for maintenance turnaround
- first-pass conformance
- rework hours
- certification hold-point delay
- expensive tooling utilization
- scrap value and material expiry loss

## 7. Compliance and Regulatory Context

Typical frameworks:

- AS9100 / EN9100
- FAA / EASA maintenance and traceability requirements
- NADCAP special-process controls where applicable
- customer and airworthiness release documentation rules

## 8. Example Parametrization

Suggested `domain_attributes` fields:

- `part_family`
- `authorization_level`
- `cleanroom_class`
- `ndt_method`
- `cure_profile`
- `traceability_lot`
