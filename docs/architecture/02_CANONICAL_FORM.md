# Canonical Mathematical Form

<details>
<summary>🇷🇺 Каноническая математическая форма</summary>

Формальная спецификация текущего ядра задачи планирования SynAPS: MO-FJSP-SDST-ARC, с отдельной пометкой для будущего advisory-ML горизонта. Описаны множества, переменные, ограничения, целевая функция и робастное расширение.

</details>

## Problem Class

**Current kernel:** **MO-FJSP-SDST-ARC** — Multi-Objective Flexible Job-Shop Scheduling Problem with Sequence-Dependent Setup Times and Auxiliary Resource Constraints.

**Extended target label:** **MO-FJSP-SDST-ML-ARC** adds a future machine-learning advisory layer above the deterministic kernel. That advisory layer is not part of the current standalone runtime.

This is a generalization that subsumes classical FJSP, JSSP, flow-shop, and parallel-machine problems as special cases.

## Sets and Indices

| Symbol | Definition |
|--------|-----------|
| $\mathcal{J}$ | Set of jobs (orders) |
| $\mathcal{O}_j$ | Ordered set of operations for job $j$ |
| $\mathcal{M}$ | Set of work centers (machines) |
| $\mathcal{E}_{o}$ | Set of eligible work centers for operation $o$ |
| $\mathcal{R}$ | Set of auxiliary resources (tooling, fixtures, containers) |
| $\mathcal{T}$ | Planning horizon (discrete or continuous) |

## Decision Variables

| Variable | Domain | Meaning |
|----------|--------|---------|
| $x_{om}$ | $\{0, 1\}$ | 1 if operation $o$ is assigned to work center $m$ |
| $s_o$ | $\mathbb{R}_{\geq 0}$ | Start time of operation $o$ |
| $\pi_m$ | permutation | Sequence of operations on work center $m$ |

## Processing Time (integer reservation grain)

$$p_{om} = \begin{cases} \text{override}_{om} & \text{if } m \in \text{machine\_duration\_overrides}(o) \\ \max\!\left(1,\ \left\lceil b_o / v_m - \epsilon \right\rceil\right) & \text{otherwise} \end{cases}$$

with base duration $b_o$, machine speed $v_m > 0$ and $\epsilon = 10^{-9}$ min (`synaps.timegrain.GRAIN_EPSILON_MIN`). The tolerance absorbs IEEE-754 division noise ($21/0.7 = 30.000000000000004$ must reserve 30, not 31 minutes) and equals the checker's physical-floor tolerance, so grain and certification agree by construction. With execution modes, the selected mode's `duration_min` is used as an absolute machine override (it is **not** divided by $v_m$).

## Hard Constraints

**Assignment:** $\sum_{m \in \mathcal{E}_o} x_{om} = 1$ for every operation (with modes: exactly one (machine, mode) pair).

**Precedence (in-order chain, finish-to-start):**

$$\forall (o_i, o_{i+1}) \in \mathcal{O}_j: \quad s_{o_{i+1}} \;\geq\; s_{o_i} + \sum_{m} x_{o_i m}\, p_{o_i m}$$

Generalized edges add $\text{anchor}(o') - \text{anchor}(o) \in [\ell^{\min}, \ell^{\max}]$ for FS/SS/FF/SF anchors.

**Time windows:** $s_o \geq \lceil \max(r_j, \text{est}_o) \rceil$ (release, earliest start) and $e_o \leq \lfloor \text{lft}_o \rfloor$; $s_o \geq H_0$, $e_o \leq H_1$.

**Machine disjunction with SDST (single lane):** for operations $a \to b$ consecutive on $m$,

$$s_b \;\geq\; e_a + \sigma_m(\text{state}(a), \text{state}(b)),$$

and the setup occupies the right-justified window $[s_b - \sigma, s_b)$. A missing cross-state cell means $\sigma = 0$ (sparse SDST); `strict_setup_matrix` turns it into a violation. Machines with `max_parallel` $=L > 1$ are $L$ identical lanes when setups exist, otherwise a cumulative of capacity $L$.

**Auxiliary resources (demand $\leq$ supply, setup + processing):**

$$\forall r \in \mathcal{R},\; \forall t: \quad \sum_{o \,:\, r \in \text{req}(o),\; s_o - \hat{\sigma}_o \leq t < e_o} q_{o,r} \;\leq\; \text{pool}(r)$$

where $q_{o,r}$ is the requested quantity (of the selected mode, when modes are used) and $\hat{\sigma}_o$ the setup reserved immediately before $o$ on its machine.

**Calendars:** the occupancy $[s_o - \hat{\sigma}_o,\ e_o]$ lies inside one published shift of the machine and of every held auxiliary resource with a non-empty calendar (empty = 24/7). Adjacent shifts are *not* merged: an operation cannot straddle a shift boundary.

## Objective Vector

| Term | Formula | Status |
|------|---------|--------|
| Coverage | $\lvert\{o \text{ scheduled}\}\rvert / \lvert\mathcal{O}\rvert$ | Level-0 rank key (`objective_sort_key`) |
| $C_{\max}$ | $\max_o e_o - H_0$ | Implemented (all solvers, canonical `evaluate`) |
| $S$ | $\sum_{\text{lanes}} \sum_{\text{consecutive } (a,b)} \sigma(a, b, m)$ | Implemented |
| $M$ | material loss summed along the same transitions | Implemented |
| $T$ | $\sum_{j} \max(0,\, C_j - d_j)$, an unscheduled order completes at $H_1$ | Implemented (**unweighted**: `Order.priority` is a dispatching weight, not a tardiness weight) |
| $E$ | energy summed along the same transitions | Implemented (transition energy only) |
| $B$, $R$ | load imbalance, schedule stability | Roadmap |

The published objective is always recomputed by the single canonical evaluator (`synaps.objective.evaluate`) at the `BaseSolver` boundary; solver-internal values are telemetry.

## Scalarization Strategies

Portfolio ranking is lexicographic: $(-\text{coverage},\ C_{\max},\ \sum_k w_k F_k)$ with `DEFAULT_WEIGHTS` = makespan only.

### Hierarchical big-M objective (CP-SAT default)

With non-negative integer coefficients $c_k$ (weights multiplied by the smallest decimal scale $K \in \{1, 10, \dots, 10^6\}$ that makes them integral) and per-term upper bounds $U_k$,

$$f = C_{\max} \cdot S_B + \sum_k c_k F_k, \qquad S_B = 1 + \sum_k c_k U_k .$$

Because $0 \le \sum_k c_k F_k < S_B$, minimizing $f$ is exactly lexicographic $(C_{\max}, \sum_k c_k F_k)$, and $\lfloor B / S_B \rfloor$ is a valid makespan dual bound for any objective bound $B$. Negative weights are rejected (they break both statements). If $(H+1) S_B > 2^{62}$ the model degrades to minimizing $C_{\max}$ alone and records it.

Known divergences from `scalarize()` (audit 2026-10, A-11/A-12): the `makespan` weight is ignored by this hierarchical mode (makespan always dominates), and the material / energy coefficients act on milli-units (`material_loss_scale = energy_kwh_scale = 1000`), i.e. a weight of 1 on material weighs 1000× more than in `scalarize()`.

### $\varepsilon$-Constraint (Pareto Slice)

$$\min f_{\text{primary}} \quad \text{s.t.} \quad f_i \leq (1 + \varepsilon_i) \cdot f_i^* \quad \forall i \neq \text{primary}$$

Current shipped Pareto profiles use $\varepsilon = 0.10$ (10% relaxation).

## Makespan Lower Bound (`compute_relaxed_makespan_lower_bound`)

$\text{LB} = \max(\text{critical path},\ \text{head-tail},\ \sum_o \min_m p_{om} / \sum_m L_m,\ \text{pinned-machine load}/L_m,\ \max_o \min_m p_{om},\ \max_r \sum_o q_{o,r} \min_m p_{om} / \text{pool}(r))$.

Each component is a relaxation (setups, calendars and generalized edges are dropped), hence valid. Caveat: it uses the base / override durations and ignores execution modes; it is currently consumed only by ALNS and RHC, which refuse mode instances.

## Robust Extension (roadmap, not implemented)

For stochastic parameters $\xi$ (processing time variance, machine failures, demand uncertainty):

$$J_{\text{robust}} = \mathbb{E}[J(\xi)] + \lambda\, \text{CVaR}_\alpha(J(\xi)) + \mu\, \Delta_{\text{stability}}$$

- $\lambda$ controls risk aversion (CVaR weight)
- $\alpha$ is the CVaR confidence level (typically 0.05–0.10)
- $\mu$ penalizes schedule instability under perturbation

## Incremental Repair Formalization

Given a disruption affecting subset $\mathcal{D} \subset \mathcal{O}$:

1. **Freeze** all assignments outside the affected subgraph
2. **Re-solve** only $\mathcal{D}$ plus its immediate predecessors/successors
3. **Measure** repair blast radius: $\Delta_{\text{repair}} = |A_{\text{new}} \triangle A_{\text{old}}| / |A_{\text{old}}|$
4. **Reject** if $\Delta_{\text{repair}} > \epsilon_{\text{max}}$ (configurable threshold)

## Determinism and Replay

For a fixed input snapshot, policy profile, and random seed:

$$R_{\text{det}} = \frac{N_{\text{identical outputs}}}{N_{\text{replays}}}$$

Target for deterministic lane: $R_{\text{det}} \geq 0.999$. CP-SAT `determinism="strict"` (single thread) and `"strict-parallel"` (interleaved subsolvers) both stop on machine-independent deterministic time; see ADR-0001.


## Repair-Radius Formalization

| Disruption Type | Radius Formula | Typical Cardinality |
|----------------|----------------|---------------------|
| `BREAKDOWN` | $R = 2 \times |\text{downstream\_setup\_chain}|$ | 10–50 ops |
| `RUSH_ORDER` | $R = \{o : |t_o - t_{\text{disrupt}}| \leq 30\text{ min}\}$ | 5–20 ops |
| `MATERIAL` | $R = \{o : \text{state}(o) \in \text{same\_group}\}$ | Variable |
| `DEFAULT` | $R = 5$ operations forward | 5 ops |

**Stability metric**: $\text{Nervousness} = |\text{moved\_ops}| / |\text{total\_ops}| \leq 5\%$.


## Special Cases

| If you restrict... | You get... |
|--------------------|-----------|
| $\lvert\mathcal{E}_o\rvert = 1$, $\sigma = 0$, $\mathcal{R} = \emptyset$ | Classical job shop $J \Vert C_{\max}$ |
| ... and every job visits the machines in the same order | (non-permutation) flow shop $F \Vert C_{\max}$ |
| One operation per job, identical machines | Identical parallel machines $P \Vert C_{\max}$ |
| One operation per job, machine-dependent $p_{om}$ | Unrelated parallel machines $R \Vert C_{\max}$ |
| $w_{\text{tardiness}}$ only, coverage full | Total tardiness minimization (makespan still dominates in the CP-SAT hierarchical mode) |
| $\sigma = 0$ | Setup-free FJSP |
| $\mathcal{R} = \emptyset$ | No auxiliary resource constraints |
