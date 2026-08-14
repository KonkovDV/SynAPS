# Cable / Wire Domain Guide

> **Scope**: Length-based cable and wire manufacturing encoded onto the SynAPS MO-FJSP-SDST-ARC kernel. Public plant narrative (Moskabelmet / MOSITLAB INFIMUM, August 2026) is a *requirements source*, not a live-factory validation and not a claim that SynAPS replaces INFIMUM.

<details><summary>🇷🇺 Краткое описание</summary>

Кабель — гибрид непрерывного потока (волочение, экструзия) и дискретной тары (барабан, калибр). Ядро SynAPS не знает метров и нарезки бухты. Адаптер пишет длительность из L/v, режет заказ на sub-reel до солвера, а KPI Dmax считает барабаны в НЗП шире, чем Cumulative aux. Заморозка 72 ч — межпрогонная политика IncrementalRepair, не RHC sealed window.
</details>

---

## 1. Domain Frame

Jobs are make-to-order lengths (metres), not piece counts. A customer order of length \(L_j\) is pre-split into sub-reels of capacity \(L_{\text{reel}}\) (Zhu et al., *Processes* 14(5):769, 2026). Each sub-reel is its own SynAPS `Order` (linear `predecessor_op_id` cannot express two parallel reels inside one order). Stages are typically drawing → stranding → extrusion → sheathing/test. Work centers are alternative machines per stage (hybrid flexible flow shop).

Moskabelmet public facts (CFO Russia 08.10.2025; Ruscable 2022; INFIMUM 2.0 / GIA 2025; Ruscable Insider 2026-08-03): 2–3% standard SKU margin, materials ~80% of cost, 4–25 process stages, 10–15 of 100 quotes become orders, 3-day plan freeze cut drums 80→61 in a LEAN pilot. Treat vendor APS numbers (39k ops / 40 min, +78M RUB, 27 days) as marketing, not a SynAPS benchmark.

## 2. SDST Mapping

| Canonical setup concept | Cable realization |
|-------------------------|-------------------|
| State-to-state change | Conductor × insulation × colour × section |
| Setup time | Head/screw/colour change, compound purge, calibrator swap |
| Material loss | Start-up length, colour-transition scrap, regulated purge metres |
| Energy penalty | Extruder heat-up, crosslinking, idle hold |

Parametric defaults in `synaps/domains/cable/adapter.py` are **the same order of magnitude** as published SMED (MAPRE clean hundreds of minutes: colour ~240, section ~360, compound/family ~400). They are a **parametric order**, not Moskabelmet stopwatch data and not a calibrated factory SMED study. Change the numbers in the adapter; do not treat 240/360/400 as plant truth.

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Line ready, last SKU still loaded |
| `processing` | Continuous length running onto a take-up drum |
| `setup` | Colour / section / compound change |
| `blocked` | Waiting for drum, crane, calibrator, or downstream cool |
| `maintenance` | Planned head/screw service |

`State.code` = `{conductor}-{insulation}-{color}-{section_mm2}` via `state_code`.

## 4. Setup Matrix Semantics

Drivers, in decreasing penalty in the adapter:

1. insulation / compound family (purge + heat)
2. conductor cross-section (tooling / head)
3. colour (masterbatch)
4. conductor metal (Cu/Al)

Same-state transitions are 0. Family clustering (campaign windows) is how “10× fewer launches” is *approximated* without illegal cross-order predecessors.

## 5. Auxiliary Resources

| Resource | Kernel encoding | Honesty gap |
|----------|-----------------|-------------|
| Take-up / pay-off drums | `AuxiliaryResource` type `drum`, required on every stage | Cumulative occupies `[start−setup, end)` only. Plant drums stay in WIP until the next stage or ship. KPI `peak_wip_drums` measures the wider span. Kernel C5a (hold-until-successor) is gated. |
| Calibrators / dies | extra aux pools (not in the default generator) | Same processing occupancy |
| Crane / AMR | extra aux (Processes 2025 special-cable AMR paper) | Out of default instance |
| Warehouse hold | not modelled | Prysmian Alesea / Aucxis RFID (Emmen, 2026-08) is IoT, not APS |

## 6. KPI Palette

| KPI | SynAPS | Plant analogue |
|-----|--------|----------------|
| Coverage / FEASIBLE notary | hard | “the plan is executable” |
| Weighted tardiness | `evaluate` | due-date / ATP |
| Setup minutes + `material_loss` | `evaluate`; `CABLE_PVC_WEIGHTS` | INFIMUM “наладочные длины” |
| `peak_wip_drums` | `cable_kpis` only | freeze −24% drums; INFIMUM tare turnover |
| Hamming \(R\) | `assignment_hamming` | INFIMUM shift continuity |
| Makespan | demoted in `cable_pvc` | secondary |

`DEFAULT_WEIGHTS` stays makespan-first. Named profile `CABLE_PVC_WEIGHTS` does not change the universal default.

## 7. Compliance and Regulatory Context

- Cable specs / GOST / IEC construction (PDM problem: 1С:КоМод at Moskabelmet, ADVARIS PDM elsewhere)
- Metal accounts (LME / DEL) — ERP, not this kernel
- Traceability of length + drum ID (MES / RFID)
- ISO 9001; fire-safety and CPR marking where applicable

APS without PDM and shop-floor length actuals is blind. SynAPS does not ingest 1С or MES in this domain drop.

## 8. Example Parametrization

Reference: [cable.json](../../schema/examples/cable.json)

Suggested `domain_attributes`:

- `conductor`, `insulation`, `color`, `section_mm2`
- `length_m`, `reel_id`, `parent_order_ref`
- `line_speed_m_per_min`, `stage`
- `hold_semantics: processing_only` on drum aux

Generator: `synaps.domains.cable.generate_cable_instance`. CLI:
`python -m synaps cable-demo` (tiny) and `python -m synaps cable-nervous-month`
(30-day synthetic pack). Measured 20 316-op month:
[CABLE_NERVOUS_MONTH_ACCEL_2026_08.md](../rfc/CABLE_NERVOUS_MONTH_ACCEL_2026_08.md).

## 9. Market of solutions (August 2026)

This is a **category map**, not a bake-off. No independent replay of vendor runtimes.

| System | What it actually sells | Cable-specific? | Relation to SynAPS |
|--------|------------------------|-----------------|--------------------|
| **ADVARIS Cable** (DE, since 1997) | PDM+ERP+MES+APS for *length-based* manufacturing: spool/length planning, drum loan accounts, metal billing, setup by diameter/colour/insulation, split/merge at drum level | Yes — the reference commercial stack | Feature checklist for C5; not OSS |
| **Asprova** | Generic APS; electrical-cable e-learning: insulation changeover, laid-up wires, setup operators, ATP | Configurable, not a cable physics kernel | ATCS-like sequencing analogue |
| **INFIMUM 2.0 (MOSITLAB)** | In-house APS at Moskabelmet. 7 criteria; published extras: setup scrap, shift continuity, tare turnover; lot combining by due-date similarity | Yes, closed, unpublished algebra | Requirements source. 39k/40 min is not a SynAPS target |
| **1С:ERP + MES** | Samara Cable Company (СКК) 2020–21: operational planning in 1С:ERP with cable-specific operation planning; not a finite-capacity metaheuristic | ERP/MES | PDM/fact layer SynAPS does not replace |
| **Siemens Opcenter / Preactor, ORSOFT, Infor SyteLine APS** | Generic finite-capacity APS glued to ERP | No drum/length native | Portfolio pattern only |
| **Prysmian Fast Track** (Calais, Dassault) | MES / MOM, not APS. Alesea + Aucxis RFID (Emmen, 12 Aug 2026): drum cycle −25% claimed via *visibility*, not sequencing | IoT + MES | Confirms drums are a logistics object |
| **Nexans** | Multi-site MES/SCADA (AVEVA-class) digitalisation | Execution, not APS | Same split: MES ≠ APS |

Honest market sentence: **there is no open-source cable APS**. There is a mature closed length-based suite (ADVARIS), generic APS (Asprova/Opcenter), Russian in-house INFIMUM, and ERP/MES. SynAPS is a kernel plus an adapter, not a fourth ERP.

## 10. Other plants and papers

| Source | What to copy | What not to copy |
|--------|--------------|------------------|
| Moskabelmet LEAN/ФЦК | 3-day freeze before any new solver | Claim −24% drums on synthetic data |
| СКК + 1С:ERP | Length/operation NSI in ERP | Treat ERP planning as FJSP |
| Prysmian Emmen 2026 | Drum as a tracked asset | Put RFID into the kernel |
| Zhu et al. 2026 HFFS | \(n_j=\lceil L_j/L_{\text{reel}}\rceil\), sub-reel sequence, energy, VNS repair 18h→0.83h | ACO-VNS as the 50k engine; −9.8% makespan as SynAPS evidence |
| Mathematics 13(8):1235 (2025) ACO cable | Feasible construction then ACO | 3-day→2.69-day toy |
| Processes 13(12):3992 (2025) special-cable AMR | Transport coupling | Default PVC generator |

## 11. Open source (thoughtfully)

| Piece | License / role | Use in this drop |
|-------|----------------|------------------|
| OR-Tools CP-SAT | already in SynAPS | Exact oracle on tiny cable fixtures |
| PyJobShop (Lan & Berkhout 2025, MIT) | FJSP+SDST+blocking+no-wait | Constraint-class reference; blocking is C5b, not shipped |
| Timefold (Apache-2) | industrial LS, nervousness | UX/repair reference, not vendored |
| TU/e JSS 2026 env | dispatch / GA / DRL bench | DRL still not SDST+aux at 10⁴ |
| dmorill FJSSP-SDST | GPL-3 | Wave 10 **forbid** |

## 12. Algebra encoded now vs gated

Encoded:

- \(p_o = \max(1,\lceil L_{\text{reel}}/v_{\text{stage}}\rceil)\) written to `base_duration_min`
- SDST \(\sigma\) from SKU deltas + `material_loss` scrap metres
- Drum Cumulative on processing window
- Campaign: `earliest_start` snapped to the earliest **release** in a family×due slot (not to the due date). Optional `colour_phase` shifts that gate by a deterministic colour/insulation slot (0–2) without passing the due date.
- Freeze: `start_time < freeze_horizon_end` subtracted from repair neighbourhood (rush cannot steal; breakdown of that op still can). `allow_freeze_break` is a **boolean policy flag**, not an ACL: any caller can set it true. First-solve pin: `solve_schedule(..., issued_assignments=..., freeze_horizon_end=...)` collapses freeze-window ops to the issued machine and interval (`pin_issued_plan`).
- Family-dedicated lines: optional `family_dedicated_lines` splits PVC vs XLPE `eligible_wc_ids` when a stage has ≥2 machines. Opt-in only: an even split halves per-family capacity and is measured infeasible at 16 machines/stage on the nervous mix.
- COVER ready rule: FIFO is the default everywhere (`cover_ready_rule="fifo"`). ATCS among ready ops exists as an opt-in (`"atcs"`, native + Python parity) but is **measured to collapse month-scale coverage** (2026-08-14 probe matrix in `docs/rfc/CABLE_NERVOUS_MONTH_ACCEL_2026_08.md`) — do not enable for production cover.
- \(D_{\max}\) and Hamming \(R\) as **functionals**, not CP-SAT terms
- CP-SAT/ALNS search may take `CABLE_PVC_CPSAT_WEIGHTS` (integer scale of `CABLE_PVC_WEIGHTS`). GREEDY default is unchanged.

Gated (C5, separate RFC): hold-until-successor aux, blocking/no-wait, reel-split as a *decision*, cross-order material tokens. Blocking/no-wait/AMR/RFID stay out of the kernel; PyJobShop is the constraint-class reference.

Hard FEASIBLE contract unchanged. Grain unchanged. No AVX-512.
