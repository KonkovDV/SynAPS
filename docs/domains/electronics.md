# Electronics Domain Guide

> **Scope**: PCB, SMT, semiconductor-adjacent, and electronics assembly lines with high-mix changeovers.

<details><summary>🇷🇺 Краткое описание</summary>

В электронике SDST определяется сменой кассет компонентов, профилей печи, программ AOI/ICT и оснастки. Каноническая модель остается той же, но значения setup_minutes и auxiliary resources описывают переналадку линий SMT, тестовых станций и чистых производственных зон.
</details>

---

## 1. Domain Frame

Jobs are PCB lots, assembly orders, test queues, or semiconductor processing lots. Work centers include screen printers, pick-and-place machines, reflow ovens, AOI stations, ICT testers, conformal coating lines, and packing cells.

## 2. SDST Mapping

| Canonical setup concept | Electronics realization |
|-------------------------|-------------------------|
| State-to-state change | Board family or BOM family change |
| Setup time | Feeder reload, stencil swap, recipe change, AOI retuning |
| Material loss | Scrap boards, solder paste purge, feeder residue |
| Energy penalty | Oven stabilization, nitrogen atmosphere reset |

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Line is ready with loaded recipe |
| `processing` | Placement, soldering, testing, or coating in progress |
| `setup` | Feeder or recipe change is underway |
| `blocked` | Waiting for materials, feeders, or upstream batch |
| `maintenance` | Calibration, preventive maintenance, or nozzle service |

## 4. Setup Matrix Semantics

The setup matrix commonly depends on:

- component family overlap between BOMs
- stencil and fixture family
- oven thermal profile
- required inspection or test program
- change in board dimensions or pallet type

## 5. Auxiliary Resources

- feeders and nozzles
- stencils and fixtures
- test adapters and ICT fixtures
- nitrogen or compressed-air capacity
- certified operators for line setup and QA sign-off

## 6. KPI Palette

- throughput per line
- setup minutes per board family
- first-pass yield
- defect escape rate
- test station utilization
- WIP age and queue depth

## 7. Compliance and Regulatory Context

Common standards:

- IPC-A-610 and IPC-J-STD-001
- ISO 9001
- ESD control requirements such as ANSI/ESD S20.20
- customer-specific electronics manufacturing quality clauses

## 8. Example Parametrization

Reference schema example: [electronics.json](../../schema/examples/electronics.json)

Suggested `domain_attributes` fields:

- `board_family`
- `bom_overlap_score`
- `reflow_profile`
- `stencil_family`
- `inspection_program`
- `esd_zone`
