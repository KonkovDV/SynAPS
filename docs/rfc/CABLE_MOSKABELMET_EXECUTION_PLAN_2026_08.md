# Cable domain execution plan — Moskabelmet pain (August 2026)

- **Status:** C0–C4 encode-first implemented 2026-08-14. C5 still gated. Not a kernel-change RFC.
- **Date:** 2026-08-14
- **Repo:** SynAPS standalone (`C:\plans\SynAPS`). GridPlan is out of scope.
- **Claim boundary:** public plant narrative + SynAPS algebra/code. Not live-factory validation. Not INFIMUM replacement. Not SOTA / N-1 / SAIDI.

## North star

Make SynAPS produce **feasible cable-structured schedules** whose KPIs move in the same direction as the published Moskabelmet LEAN/APS story: fewer setups and setup scrap, bounded plan nervousness, and fewer drums in WIP — **without pretending that 500k synthetic coverage is that story**.

Success is a **named policy profile** (`cable_pvc`) plus a **synthetic cable generator** where:

1. `status == FEASIBLE` under the hard notary (exhaustive checker, stabilize `converged == 1`, no overflow past `planning_horizon_end`).
2. A 72-hour freeze plus rush-admission reduces peak WIP-drums versus unrestricted insert (directionally the plant’s −24% drums after a 3-day freeze).
3. A cable weight vector beats makespan-only on setup scrap and drum-WIP on the same instance.
4. No factory MES/1С data is required for C0–C4. C5 is gated on C2/C4 evidence, not on ambition.

## Non-goals

| Forbidden | Why |
|-----------|-----|
| Treat INFIMUM 39k ops / 40 min as a SynAPS target | Different model, unpublished algebra, vendor claim |
| Treat 499 770 ops / 145 s GREEDY_COVER as cable evidence | Synthetic coverage, default aux semantics |
| Replace 1С:КоМод / MES | APS is blind without PDM and shop-floor facts |
| GridPlan / ROSSETI / N-1 | Different product |
| Vendor dmorill FJSSP-SDST (GPL-3) | Wave 10 permanent forbid |
| AVX-512, rayon on the main cover loop | Raptor Lake hybrid CPU contract |
| DRL as the factory engine | 2026 literature still fails SDST+aux at 10⁴–10⁵ |
| Cross-order `predecessor_op_id` in C0–C4 | Validator rejects it; campaign combining is a preprocessor until C5d |

## Encode-first rule

Plant physics maps to **MO-FJSP-SDST-ARC** through an adapter. Kernel changes need a new RFC + Red Team and only open when an encode path is proven insufficient.

```
domain process  →  adapter (states, durations, aux, freeze)  →  existing kernel
                                                              ↘ C5 only if KPI gap remains
```

### What the kernel already isomorphs

| Plant lever | Existing code | Gap |
|-------------|---------------|-----|
| Color / head / section changeover | `SetupEntry.setup_minutes` + `material_loss` + `energy_kwh` | Adapter must emit family×color×section states; SMED minutes are parameters, not baked constants |
| Drums / calibrators / crane as capacity | `AuxiliaryResource` + Cumulative on `[start−setup, end)` | Occupancy **ends when the op ends**. Plant drums stay as WIP until the next stage or shipment |
| 4–25 stages | `predecessor_op_id` chain inside one order | Cross-order WIP feed is illegal today |
| Due dates / rush windows | `Order.due_date`, `earliest_start` / `latest_finish` | Unused `Order.quantity` — solvers never turn metres into `p_o` |
| “Do not touch issued plan” | RHC `sealed_window_op_ids`; `incremental_repair` + `recommend_repair_radius` | RHC freeze is **intra-solve commit**, not a 72-hour **business** freeze |
| Setup scrap in the objective | `evaluate()` `total_material_loss`; CP-SAT/ALNS honor weights | `DEFAULT_WEIGHTS` is makespan-only |
| Schedule stability \(R\) | Canonical form `02_CANONICAL_FORM.md` (roadmap) | Not in `ObjectiveValues` |
| Load / WIP \(B\) | Same roadmap | Not in `ObjectiveValues` |

### What must not be faked as “already supported”

- Reel-splitting as a **decision** (Zhu et al., *Processes* 14(5):769, 2026). C2 **pre-splits** \(n = \lceil L_{\text{order}} / L_{\text{reel}} \rceil\) before solve.
- Lot combining across orders (“10× fewer launches”). C3 clusters by state; it does not merge foreign predecessors.
- Blocking / no-wait on extrusion→cooling. PyJobShop has the constraint class; SynAPS does not. C5b.
- Drum **cycle time** (warehouse hold). C2 measures it as a schedule functional; C5a optimizes it only if C4 cannot.

## Algebra (locked)

Hard FEASIBLE contract is unchanged. Grain remains `max(1, ceil(base/speed))`.

Cable-specific **schedule functionals** (C2, not yet search terms):

\[
W_{\text{reel}}(c) = C_{\text{last}(c)} - S_{\text{first}(c)}
\]

\[
D(t) = \bigl|\{ c : S_{\text{first}(c)} \le t < C_{\text{last}(c)} \}\bigr|, \quad D_{\max} = \max_t D(t)
\]

where \(c\) is a reel-chain (`domain_attributes.reel_id`). This is **WIP drum count**, not Cumulative pool size during processing.

Stability (C4, canonical \(R\)):

\[
R = \frac{|A_{\text{new}} \triangle A_{\text{old}}|}{|A_{\text{old}}|}
\]

Gated kernel C5a (`wip_token` aux): occupy \([s_o-\hat\sigma_o,\; s_{\text{succ}(o)})\) instead of \([s_o-\hat\sigma_o,\; s_o+p_o)\). Last op holds until order completion \(C_j\). This changes checker, native cover, and CP-SAT Cumulative together (atomic delivery).

## Waves

Pipeline: **C0 → (C1 ∥ C2) → C3 → C4 → evidence gate → C5**.

Do not start C5 because C4 “feels incomplete”. Open C5 only if cable-profile search still cannot cut \(D_{\max}\) / \(R\) after freeze + campaign sort.

### C0 — Domain contract

**Intent:** cable is a catalogued domain, not a research anecdote.

| Deliverable | Path |
|-------------|------|
| Domain guide | `docs/domains/cable.md` (same sections as metallurgy) |
| Example payload | `schema/examples/cable.json` |
| Catalog row | `docs/domains/DOMAIN_CATALOG.md` (domain 9) |
| Tiny fixture | `tests/fixtures/cable_pvc_small.json` |
| Generator | `synaps/benchmarks/cable_instance.py` (or a flag on `instance_generator`) |

**State dictionary:** `(conductor, insulation, color, section_mm²)` → `State.code`.  
**Aux types:** `drum_<flange>`, `calibrator`, `crane`.  
**Duration:** adapter writes `base_duration_min = ceil(length_m / line_speed_m_per_min)`; kernel still ignores `Order.quantity`.

**Exit:** 9th catalog domain; example + fixture solve `FEASIBLE` on GREEDY; no factory numbers claimed as measurements.

### C1 — Business freeze and rush admission

**Intent:** the plant’s highest published APS-adjacent lever (−24% drums after a 3-day freeze) is policy, not a new metaheuristic.

| Deliverable | Path |
|-------------|------|
| Policy fields | `freeze_horizon_end` on solve/repair request (or `domain_attributes.planning_policy`) |
| Mapping | assignments with `end_time < freeze_horizon_end` → `immutable_op_ids` |
| Rush gate | `SolveRegime.RUSH_ORDER` may not steal freeze-window machines without `allow_freeze_break=true` |
| Tests | insert-after-freeze keeps Hamming on frozen set = 0; checker flags moves |

RHC `sealed_window_op_ids` stays the intra-solve commit mechanism. C1 is **inter-solve** policy on top of incremental repair.

**Exit:** synthetic rush-into-busy-week: frozen prefix identical; \(D_{\max}\) and setup scrap do not explode versus the no-freeze baseline. Directional, not a claim of −24%.

### C2 — Physics adapter (no kernel)

**Intent:** a cable instance is physically cable-shaped.

- Pre-split each order into reel ops: `n_reels = ceil(length_m / L_reel)`, sequential predecessors, shared `reel_id`.
- SDST from a parametric family matrix (color change ≫ section change ≫ same-family). Do not hardcode Moskabelmet SMED 405→346 as truth.
- KPI module `synaps/domains/cable/kpis.py`: \(D_{\max}\), reel WIP hours, setup metres, tardiness, Hamming vs baseline.
- Generator knobs: SKU families, 4–25 stages, drum pool, flexibility, freeze horizon.

**Exit:** 5k-op cable instance `FEASIBLE`; KPI JSON emitted; processing-aux peak and WIP \(D_{\max}\) both reported so the occupancy gap is visible.

### C3 — Campaign preprocessor

**Intent:** approximate “fewer launches” without illegal cross-order edges.

- Cluster ready ops by `state_id` / family.
- Release/sort so ATCS sees long same-state runs (SDST = 0 inside a family).
- Do **not** merge two customer orders into one `Order` if due dates or genealogy must stay separate.
- Optional: campaign windows as `earliest_start` batches — still one order per customer.

**Exit:** same C2 instance, campaign sort vs random arrival: fewer setup events and lower `total_material_loss` at equal coverage.

### C4 — Cable objective profile

**Intent:** stop optimizing the wrong scalar.

| Term | Status now | C4 action |
|------|------------|-----------|
| Coverage | Level-0 in `objective_sort_key` | Unchanged |
| Tardiness / setup / material / energy | In `ObjectiveValues`; default weights 0 except makespan | Profile `cable_pvc` turns them on |
| Stability \(R\) | Roadmap only | `evaluate(..., baseline=)` + weight `stability` |
| Drum WIP \(D_{\max}\) | C2 KPI only | Promote to `ObjectiveValues.peak_wip_drums` **or** keep as external score if CP-SAT encoding is too heavy; ALNS/greedy can use it immediately |

Named profile, **not** a change to `DEFAULT_WEIGHTS` (makespan-first remains the universal default).

Lex suggested for `cable_pvc`: coverage ≻ tardiness ≻ material ≻ stability ≻ \(D_{\max}\) ≻ makespan.

**Exit:** on the C2 generator, `cable_pvc` vs makespan-only: material and \(D_{\max}\) improve; coverage stays 1.0; FEASIBLE notary still empty. Schemas regenerated if `ObjectiveValues` grows.

### C5 — Kernel extensions (gated)

Open a **separate** RFC per bullet. Atomic delivery: model + checker + every solver that can emit the construct + native path + tests. Helpers ≤ 80 lines; function-length ratchet slack +10.

| ID | Change | Open when |
|----|--------|-----------|
| **C5a** | `wip_token` hold-until-successor aux | C2 shows \(D_{\max}\) ≫ processing-pool peak **and** C4 weights cannot close it |
| **C5b** | Blocking / no-wait (PyJobShop-class) | Extrusion→cool buffer is binding on the generator, not just theoretically |
| **C5c** | Reel-split as a decision variable (Zhu 2026) | Fixed \(L_{\text{reel}}\) pre-split leaves systematic leftover length or forced extra drums |
| **C5d** | Cross-order material tokens | Campaign preprocessor cannot express shared semi-finished drums without lying about `order_id` |

C5a sketch (do not implement in C0–C4):

\[
\forall r\in\mathcal{R}_{\text{wip}},\; \forall t:\quad
\sum_{o: r\in\mathrm{req}(o),\; s_o-\hat\sigma_o \le t < s_{\mathrm{succ}(o)}} 1 \le \mathrm{cap}(r,t)
\]

Native `list_schedule_cover` must delay on token release, not only on machine tail. No AVX-512.

## Evidence protocol

| Claim | Allowed evidence | Forbidden evidence |
|-------|------------------|--------------------|
| Adapter works | Fixture + 5k cable `FEASIBLE` + KPI JSON | Factory MES dump we do not have |
| Freeze helps drums | Paired synthetic: freeze vs insert-anywhere, same seed | INFIMUM +8% output |
| Cable weights help | Paired: `cable_pvc` vs default weights | 500k GREEDY_COVER wall time |
| Kernel C5 needed | C4 Pareto: \(D_{\max}\) or \(R\) stuck after freeze+campaign | “literature has reel-splitting” |

Three numbers that must never be added: SynAPS synthetic coverage time, INFIMUM vendor latency, Zhu 2026 HFFS −9.8% makespan.

Scale for cable evidence: **5k–40k** cable-structured ops. 100k–500k remains a separate coverage track.

## OSS posture

- Keep OR-Tools CP-SAT as the exact oracle on ≤ hundreds of ops (and on C5b prototypes).
- Use PyJobShop (MIT, 2025) as a **constraint-class reference** for blocking/no-wait, not as a vendored engine.
- Timefold as a **repair/nervousness UX reference**, not a Python rewrite.
- TU/e dispatching rules already have an analog (ATCS in greedy).
- Do not vendor GPL packs.

## Blast radius (when implementation starts)

Expected C0–C4 files (illustrative, not a license to drive-by refactors):

- `docs/domains/cable.md`, `DOMAIN_CATALOG.md`, `schema/examples/cable.json`
- `synaps/benchmarks/cable_instance.py`, `synaps/domains/cable/kpis.py`
- `synaps/model.py` / contracts only if freeze fields or `ObjectiveValues` grow (C1/C4)
- `synaps/objective.py`, `synaps/solvers/incremental_repair.py`, router/repair request
- `tests/test_domain_cable.py`, freeze/rush tests, KPI tests

C5 additionally: `feasibility_checker.py`, `cpsat_solver.py`, `native/synaps_native/src/list_schedule.rs`, ALNS/RHC cover.

## Order of work for the next session

C0–C4 and 8-stage cover are shipped. Next wave is C6, not a replay of C0.

1. **C6a** multiseed 1..5 cover+notary @1600×8 — **done 2026-08-15**.
2. **C6b** freeze vs insert \(D_{\max}\) on seeds 1 and 2 — **done 2026-08-15**.
   Occupancy 21 ≪ pool 48; WIP Δ sign flips. C5a stays gated.
3. **C6c** weighted residual/ALNS on 1600@8 — **done 2026-08-15**.
   PVC tardiness 48 056–164 080; scalar beat makespan residual 4/5 seeds.
4. **C6d / C5a** only if occupancy hits the pool. Do not ingest 1С.

See `docs/rfc/CABLE_C6_POST_OSINT_PLAN_2026_08_15.md`.

Estimated effort if executed continuously: C0 1–2 d, C1 2–4 d, C2 3–5 d, C3 2–3 d, C4 3–5 d, C5a 1–2 w after a written gate.

## Implementation note (2026-08-15)

Shipped encode-first: domain 9 + generator + KPIs + campaign windows +
`CABLE_PVC_WEIGHTS` + IncrementalRepair freeze. Nervous-month evidence:
20 316 ops `feasible` at 16 machines/stage (windowed ATCS, tardiness 1 922)
and at 8/stage (family flex + 6-colour wheel + continuation exhaust stay).
C6a seeds 1..5 @8: all COVER-feasible, notary 0; tardiness 48 269–164 355
(median 87 134). C6b freeze-pair seeds 1–2: freeze FEASIBLE; rush WIP Δ
−66 / +40; occupancy 21 ≪ pool 48. C6c weighted ALNS residual (60 s,
destroy 20): PVC tardiness 48 056–164 080 (Δ −478..−25 vs cover); scalar
beat makespan residual 4/5. C6-R1 `waves=4` plumbing shipped; seed 2
was `INFEASIBLE` once (notary=1). C5a still gated. Do not claim weekly
freeze holds at 8-stage.
Plan/RT:
`docs/rfc/CABLE_C6_POST_OSINT_PLAN_2026_08_15.md`,
`docs/rfc/CABLE_C6_PLAN_REDTEAM_2026_08_15.md`,
`docs/rfc/CABLE_C6C_REDTEAM_2026_08_15.md`,
`docs/rfc/CABLE_C6R1_REDTEAM_2026_08_15.md`.

