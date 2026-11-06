# Cable / Wire Domain Guide

> **Scope**: Length-based cable and wire manufacturing encoded onto the SynAPS MO-FJSP-SDST-ARC kernel. A public plant narrative is a requirements sketch, not a live-factory validation and not a claim that SynAPS replaces a vendor product.

<details><summary>🇷🇺 Краткое описание</summary>

Кабель — гибрид непрерывного потока (волочение, экструзия) и дискретной тары (барабан, калибр). Ядро SynAPS не знает метров и нарезки бухты. Адаптер пишет длительность из L/v, режет заказ на sub-reel до солвера, а KPI Dmax считает барабаны в НЗП шире, чем Cumulative aux. Заморозка 72 ч — межпрогонная политика IncrementalRepair, не RHC sealed window.
</details>

---

## 1. Domain Frame

Jobs are make-to-order lengths (metres), not piece counts. A customer order of length \(L_j\) is pre-split into sub-reels of capacity \(L_{\text{reel}}\) (Zhu et al., *Processes* 14(5):769, 2026). Each sub-reel is its own SynAPS `Order` (linear `predecessor_op_id` cannot express two parallel reels inside one order). Stages are typically drawing → stranding → extrusion → sheathing/test. Work centers are alternative machines per stage (hybrid flexible flow shop).

Public plant and vendor stories are a requirements sketch, not a measurement and not a customer record. Do not cite a holding, a street address, a ruble figure, or a vendor stopwatch as a SynAPS result. The non-claim note is [CABLE_MOSKABELMET_OSINT_REDTEAM_2026_08_15.md](../rfc/CABLE_MOSKABELMET_OSINT_REDTEAM_2026_08_15.md).

## 2. SDST Mapping

| Canonical setup concept | Cable realization |
|-------------------------|-------------------|
| State-to-state change | Conductor × insulation × colour × section |
| Setup time | Head/screw/colour change, compound purge, calibrator swap |
| Material loss | Start-up length, colour-transition scrap, regulated purge metres |
| Energy penalty | Extruder heat-up, crosslinking, idle hold |

Parametric defaults in `synaps/domains/cable/adapter.py` are **the same order of magnitude** as published SMED (MAPRE clean hundreds of minutes: colour ~240, section ~360, compound/family ~400). They are a **parametric order**, not a plant stopwatch and not a calibrated factory SMED study. Change the numbers in the adapter; do not treat 240/360/400 as plant truth.

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
| Take-up / pay-off drums | `AuxiliaryResource` type `drum`, required on every stage | Three peaks, not one: `peak_wip_drums` = reel span first→last stage; `peak_processing_drums` = `[start, end)`; `peak_aux_hold_drums` = `[start−setup, end)` (checker F1 / Cumulative window). C6b 1600@8 quoted **processing 21** vs pool 48 vs **span 155–222**. C5a (hold-until-successor) is gated — it would push occupancy toward span, not toward processing. |
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
| `peak_processing_drums` | `cable_kpis` only | processing occupancy `[start, end)`; C6b = 21 @1600×8 |
| `peak_aux_hold_drums` | `cable_kpis` only | Cumulative window `[start−setup, end)`; not C5a |
| Hamming \(R\) | `assignment_hamming` | INFIMUM shift continuity |
| Makespan | demoted in `cable_pvc` | secondary |

`DEFAULT_WEIGHTS` stays makespan-first. Named profile `CABLE_PVC_WEIGHTS` does not change the universal default.

## 7. Compliance and Regulatory Context

- Cable specs / GOST / IEC construction (a PDM problem; not this kernel)
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
Next wave: [CABLE_C6_POST_OSINT_PLAN_2026_08_15.md](../rfc/CABLE_C6_POST_OSINT_PLAN_2026_08_15.md).

## 9. Market of solutions (August 2026)

This is a **category map**, not a bake-off. No independent replay of vendor runtimes.

| System | What it actually sells | Cable-specific? | Relation to SynAPS |
|--------|------------------------|-----------------|--------------------|
| **ADVARIS Cable** (DE, since 1997) | PDM+ERP+MES+APS for *length-based* manufacturing: spool/length planning, drum loan accounts, metal billing, setup by diameter/colour/insulation, split/merge at drum level | Yes — the reference commercial stack | Feature checklist for C5; not OSS |
| **Asprova** | Generic APS; electrical-cable e-learning: insulation changeover, laid-up wires, setup operators, ATP | Configurable, not a cable physics kernel | ATCS-like sequencing analogue |
| **In-house cable APS** | Closed product: setup scrap, shift continuity, tare turnover, lot combining | Yes, unpublished algebra | Requirements sketch. A vendor runtime is not a SynAPS target |
| **1С:ERP + MES** | Samara Cable Company (СКК) 2020–21: operational planning in 1С:ERP with cable-specific operation planning; not a finite-capacity metaheuristic | ERP/MES | PDM/fact layer SynAPS does not replace |
| **Siemens Opcenter / Preactor, ORSOFT, Infor SyteLine APS** | Generic finite-capacity APS glued to ERP | No drum/length native | Portfolio pattern only |
| **Prysmian Fast Track** (Calais, Dassault) | MES / MOM, not APS. Alesea + Aucxis RFID (Emmen, 12 Aug 2026): drum cycle −25% claimed via *visibility*, not sequencing | IoT + MES | Confirms drums are a logistics object |
| **Nexans** | Multi-site MES/SCADA (AVEVA-class) digitalisation | Execution, not APS | Same split: MES ≠ APS |

Honest market sentence: **there is no open-source cable APS**. There is a mature closed length-based suite (ADVARIS), generic APS (Asprova/Opcenter), Russian in-house INFIMUM, and ERP/MES. SynAPS is a kernel plus an adapter, not a fourth ERP.

## 10. Other plants and papers

| Source | What to copy | What not to copy |
|--------|--------------|------------------|
| Plant LEAN program | A multi-day freeze before a new solver; shop-floor setup reduction is not APS | Do not treat a published drum delta as a SynAPS result |
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
- Drum Cumulative on `[start−setup, end)` (checker / CP-SAT). KPI `peak_aux_hold_drums` reports that window from assignment stamps; `peak_processing_drums` is `[start, end)` only.
- Campaign: `earliest_start` snapped to the earliest **release** in a SKU×due slot (not to the due date). Optional `colour_phase` staggers that gate: hash%3 (0–2 slots) when a stage has >8 machines; a 6-colour wheel (at most five slots, never past due) when ≤8. Mixing 16 mm² and 35 mm² into one colour gate interleaved section SDST and is not used.
- Freeze: `start_time < freeze_horizon_end` subtracted from repair neighbourhood (rush cannot steal; breakdown of that op still can). `allow_freeze_break` is a **boolean policy flag**, not an ACL: any caller can set it true. First-solve pin: `solve_schedule(..., issued_assignments=..., freeze_horizon_end=...)` collapses freeze-window ops to the issued machine and interval (`pin_issued_plan`).
- Family-dedicated lines: `family_dedicated_lines` splits PVC vs XLPE `eligible_wc_ids` when a stage has ≥2 machines. Line counts follow SKU-catalog share (not 50/50). One flex overflow machine when n≥3 (Schaller/Gupta family tardiness). Opt-in at 16/stage (tardiness 3 670 vs ATCS-only 1 922). Default **on** at ≤8/stage (tardiness 87 134 vs 246 509 without family on the feasible cover).
- Colour-dedicated lines: optional `colour_dedicated_lines` when a stage has ≥6 machines (2 flex at n≥8). Opt-in; tardiness at 16/stage is much worse than ATCS-only, and at 8/stage they drop coverage (0.854 vs FEASIBLE without cells).
- COVER ready rule: nervous-month COVER defaults to **windowed** ATCS with floor window 0 (non-delay). Unbounded ATCS and a 240 min delay window on *any* job both collapsed month coverage. At ≤8/stage a separate `cover_atcs_exhaust_window` (default 240) waits only for a zero-setup continuation and stays on the hot machine (Mahmoodi/Dooley 1991; Flynn 1987). The 50k/500k registry path stays FIFO (`cover_ready_rule="fifo"`). Native Kolisch SGS starts at ≥10 000 ops: build the wheel into the same interpreter that will run the probe (`py -3.13 -m maturin develop --release`). A wheel for another interpreter does not load.
- \(D_{\max}\) and Hamming \(R\) as **functionals**, not CP-SAT terms
- CP-SAT/ALNS search may take `CABLE_PVC_CPSAT_WEIGHTS` / `CABLE_PVC_WEIGHTS`. GREEDY/COVER construction is unchanged. C6c: `--weighted-residual` seeds ALNS from COVER; 1600@8 PVC residual cut tardiness 25–478 min vs cover (not ATP). C6-R1: `--waves 4` at 8/stage is **plumbing** (stop-on-dirty, wave notary kinds). Seed 2 was `INFEASIBLE` once on weeks 3–4; Hamming is path-dependent. Not a freeze-quality proof. S4: IncrementalRepair `--repair-notary {exhaustive,delta,shadow}`; default **exhaustive**; aux is always a full drum-pool TimeTable. 1600@8 shadow matched exhaustive on seeds 1–2 / four weeks; **not** the new default.

Gated (C5, separate RFC): hold-until-successor aux, blocking/no-wait, reel-split as a *decision*, cross-order material tokens. Blocking/no-wait/AMR/RFID stay out of the kernel; PyJobShop is the constraint-class reference.

Hard FEASIBLE contract unchanged. Grain unchanged. No AVX-512.
