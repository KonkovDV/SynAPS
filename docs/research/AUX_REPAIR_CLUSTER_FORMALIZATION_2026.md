# Auxiliary-Resource Feasibility Repair: Formalization and Correctness Conditions (2026-07)

> **Status**: Research note. Formal specification of the auxiliary-resource
> repair subproblem for the RHC path, grounded in four empirically-established
> barriers (iterations 4–5). No production code shipped yet — this note defines
> what a correct algorithm must satisfy before implementation.

---

## 1. Setting

The RHC solver produces a schedule that is precedence- and machine-feasible
(after the iteration-3 commit precedence gate and the final temporal
stabilizer) but retains a small residual of **auxiliary-resource capacity**
violations (industrial: 4/791, industrial-2k: 8/2082 — <1% of operations).
This note formalizes the *repair* subproblem: given a committed schedule that
violates only the aux-capacity constraint, restore full feasibility while
preserving coverage and disturbing the schedule minimally.

We reuse the canonical MO-FJSP-SDST-ARC notation (`docs/architecture/02_CANONICAL_FORM.md`).

## 2. Notation

| Symbol | Meaning |
|--------|---------|
| $\mathcal{O}$ | all operations; $\mathcal{J}$ orders; $\mathcal{M}$ work centers |
| $\mathcal{R}$ | auxiliary resources, each with pool capacity $\mathrm{cap}(r)\in\mathbb{Z}_{>0}$ |
| $\mathrm{req}(o)\subseteq\mathcal{R}$ | resources operation $o$ requires; $q_{o,r}$ the quantity |
| $s_o,\;p_o,\;\hat\sigma_o$ | start, processing time, and reserved setup ($\hat\sigma_o=0$ if first on its machine) |
| $A^0=\{(o,m_o,s_o)\}$ | the incumbent committed schedule to repair |
| $\mathcal{V}\subseteq\mathcal{O}$ | operations flagged in an `AUX_RESOURCE_CAPACITY_VIOLATION` |

The aux constraint (identical to `FeasibilityChecker` §5 and the CP-SAT
`AddCumulative` model in `cpsat_solver.py`) is, for every $r$ and time $t$:

$$\sum_{\,o\,:\,r\in\mathrm{req}(o),\;\; s_o-\hat\sigma_o \,\le\, t \,<\, s_o+p_o} q_{o,r}\;\;\le\;\;\mathrm{cap}(r). \tag{AUX}$$

The reservation window is the half-open interval $[\,s_o-\hat\sigma_o,\; s_o+p_o)$;
setup consumes the resource. (AUX) is **cumulative and global in time** — it
couples every operation touching $r$, not just precedence- or machine-adjacent
pairs. This is the structural reason it differs from precedence (a pairwise
edge constraint, closed in iteration 3).

## 3. The repair subproblem (fix-and-optimize)

Choose a **repair set** $C\subseteq\mathcal{O}$; freeze $F=\mathcal{O}\setminus C$
at its incumbent placement; re-decide $(m_o,s_o)$ for $o\in C$:

$$
\begin{aligned}
\min_{\{(m_o,s_o)\}_{o\in C}}\quad & \lVert A - A^0 \rVert \quad\text{(disturbance; or window makespan)}\\
\text{s.t.}\quad
& s_{o'} \ge s_o + p_o &&\forall (o\to o')\ \text{precedence}, \\
& \text{no-overlap}/\text{SDST on each } m &&\text{(incl. frozen intervals)}, \\
& \text{(AUX) over } C\cup F &&\forall r\in\mathcal{R}. \\
\end{aligned}
$$

This is a **fix-and-optimize** re-optimization (Relax-and-Fix / F&O family,
PMS-2026 workshop; Kasapidis et al., *EJOR* 2025 unified multi-resource FJSP
framework) and equivalently the sub-problem layer of a **logic-based Benders
decomposition** (Hooker; Xiong et al., *EJOR* 2026), where the cumulative
`AddCumulative` sub-model is the CP feasibility oracle. The engine
(`CpSatSolver`) already models precedence + no-overlap + SDST `AddCircuit` +
aux `AddCumulative` and accepts `frozen_assignments`, so the subproblem is
directly expressible.

## 4. Correctness conditions (each established by an empirical barrier)

A repair set $C$ and its subproblem yield a **globally aux-feasible** schedule
only if all three hold. Each was isolated by a failed iteration-4/5 approach.

### C1 — Resource-completeness
$$r\in\mathrm{req}(o)\ \text{for some}\ o\in C \;\Longrightarrow\; \{o'\in\mathcal{O}: r\in\mathrm{req}(o')\}\subseteq C.$$
Every operation sharing any resource touched by $C$ must be *in* $C$ (transitive
closure over shared resources). Otherwise a frozen op on $r$ is invisible to the
subproblem's cumulative and (AUX) can be violated against it.
**Barrier evidence:** the commit-time aux gate (event-sweep before the
stabilizer) left 4→6 / 8→8 violations — it never saw the post-stabilize
coupling.

### C2 — Order-completeness
$$o\in C \;\Longrightarrow\; \{o'\in\mathcal{O}: \mathrm{order}(o')=\mathrm{order}(o)\}\subseteq C.$$
$C$ must contain whole orders. The SynAPS data model requires each order's
operations to form a contiguous `seq_in_order` precedence chain; an arbitrary
resource-induced subset breaks that invariant.
**Barrier evidence:** a resource-only cluster raised
`ScheduleProblem` `ValidationError` ("must reference predecessor_op_id … based
on seq_in_order").

### C3 — Frozen-aux accounting
The subproblem's cumulative must include the fixed reservation intervals of
$F$-operations that require any $r$ touched by $C$:
$$\text{cumulative}(r) \;=\; \{\text{intervals of } o\in C\} \;\cup\; \{\text{fixed intervals of } o\in F,\ r\in\mathrm{req}(o)\}.$$
`CpSatSolver._add_aux_resource_cumulative_constraints` currently iterates only
`problem.operations` (the $C$ side); frozen machine intervals are added to the
machine no-overlap but **not** to the aux cumulative. C1 makes C3 vacuous *iff*
the closure is complete, but for partial closures C3 is the safety net.
**Barrier evidence:** point-repair via `find_earliest_feasible_slot` (which is
aux-aware only w.r.t. already-placed ops) cascaded precedence (4→3+12 /
8→6+26) because moved ops broke successors not in its local view.

> **Rejected non-viable approaches (why they violate the conditions).**
> (1) commit-time gate — runs before the stabilizer, misses C1/C3 coupling;
> (2) forward-shift stabilizer — three monotone shifts do not converge (2k
> 8→76); a cumulative constraint is not repairable by per-op forward moves;
> (3) point-repair — violates C2 (moves single ops) and cascades precedence;
> (4) naive resource cluster — violates C2 (order chain) at model-validation.

## 5. Correctness claim

**Proposition.** If $C$ satisfies **C1 ∧ C2**, and the subproblem is solved with
**C3** and frozen machine/precedence boundaries, then any feasible CP-SAT
solution spliced over $F$ is globally feasible for precedence, machine/SDST,
and (AUX).

*Sketch.* C2 ⇒ every precedence chain is either wholly in $C$ (re-decided
jointly) or wholly in $F$ (unchanged) — no dangling edge. Machine no-overlap
holds because frozen intervals are constraints in the sub-model. For (AUX): by
C1 every op touching a resource of $C$ is in $C$ and modelled in the cumulative;
by C3 any residual frozen demand on those resources is a fixed interval in the
same cumulative; ops on resources *not* touched by $C$ are untouched. Hence the
per-resource cumulative the solver enforces equals the global one. ∎

## 6. Scalability trade-off (the open engineering problem)

C1 ∧ C2 make $C$ the union of orders connected through shared resources — a
**connected component of the order–resource bipartite graph**. On dense
industrial presets (aux probability ≈ 0.4, few resources) this component can
approach the whole instance, and a CP-SAT solve with `AddCircuit` SDST +
`AddCumulative` over hundreds of operations is not reliably tractable in the
per-repair budget. The genuine research question is therefore **not** "how to
model the repair" (§3–§5 settle that) but **how to bound $C$**:

- resource-capacity **relaxation of the cut**: allow re-deciding only orders
  whose ops fall in the violating time window, treating far-away same-resource
  ops as fixed intervals via C3 (trading a complete closure for C3 coverage);
- **Benders/LBBD loop**: master picks order→machine reassignments, CP sub
  checks (AUX) on the bottleneck resource and returns nogood cuts (Xiong 2026
  DFJSP framing);
- **capacity-scaled** time discretization to keep the cumulative model small.

## 7. Next step

Implement §3 with the **windowed C3 relaxation** (bounded $C$ = whole orders
intersecting the violation time window + frozen-aux intervals for the rest),
behind an opt-in flag, and measure feasibility vs. cluster size and solve time
on industrial / industrial-2k before enabling it in any preset. Ship only if it
reaches 0 aux violations without precedence/machine regressions and within the
coverage budget.

## References

- Hooker, J.N. — *Planning and Scheduling by Logic-Based Benders Decomposition*, Operations Research.
- Xiong, F. et al. (2026) — *Logic-based Benders decomposition methods for the distributed flexible job-shop*, EJOR 329(3).
- Kasapidis, G.A. et al. (2025) — *A unified solution framework for flexible job shop scheduling with multiple resource constraints*, EJOR.
- Lan, L. et al. (2025) — *PyJobShop: Solving scheduling problems with constraint programming*, arXiv:2502.13483.
- PMS-2026 — *Relax-and-fix and fix-and-optimize for scheduling problems* (workshop proceedings).
