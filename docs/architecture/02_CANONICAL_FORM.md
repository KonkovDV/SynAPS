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

## Hard Constraints

**Supply ≤ Demand (auxiliary resources, setup + processing):**

$$\forall r \in \mathcal{R},\; \forall t \in \mathcal{T}: \quad \sum_{o \,:\, r \in \text{req}(o),\; s_o - \hat{\sigma}_o \leq t < s_o + p_{o}} 1 \;\leq\; \text{cap}(r, t)$$

where $\hat{\sigma}_o$ is the setup duration reserved immediately before operation $o$ on its assigned work center (and $\hat{\sigma}_o = 0$ when no setup is required).

**Precedence:**

$$\forall j \in \mathcal{J},\; \forall (o_i, o_{i+1}) \in \mathcal{O}_j: \quad s_{o_{i+1}} \;\geq\; s_{o_i} + p_{o_i}$$

**No-overlap (with setup):**

$$\forall m,\; \forall (o_a, o_b) \text{ consecutive on } m: \quad s_{o_b} \;\geq\; s_{o_a} + p_{o_a} + \sigma(o_a, o_b, m)$$

where $\sigma(o_a, o_b, m)$ is the sequence-dependent setup time.

**Capacity:**

$$\forall m \in \mathcal{M},\; \forall t: \quad \sum_{o: x_{om}=1,\; s_o \leq t < s_o + p_o} 1 \;\leq\; \text{cap}(m)$$

## Objective Function

$$J = w_1 T + w_2 S + w_3 M + w_4 B + w_5 R + w_6 E$$

| Term | Formula | Description | Status |
|------|---------|-------------|--------|
| $T$ | $\sum_{j} \alpha_j \max(0,\, C_j - d_j)$ | Weighted tardiness | **Implemented** (CP-SAT) |
| $S$ | $\sum_{m} \sum_{\text{consecutive } (a,b)} \sigma(a, b, m)$ | Total setup time | **Implemented** (CP-SAT, Greedy) |
| $M$ | $\sum_{o} \text{material\_cost}(o)$ | Material waste / auxiliary resource cost | **Implemented** (CP-SAT) |
| $B$ | $\text{Var}(\text{load}_m)$ or $\max(\text{load}_m) - \min(\text{load}_m)$ | Load imbalance | Roadmap |
| $R$ | $\|A_{\text{new}} \triangle A_{\text{old}}\| / \|A_{\text{old}}\|$ | Schedule stability | Roadmap |
| $E$ | $\sum_{m,t} \text{tariff}(t) \cdot \text{power}(m, t)$ | Energy cost | Roadmap |

**Weights** $w_1, \ldots, w_6$ are configurable per policy profile. Future advisory or operator surfaces may retune them, but no live ML tuner is shipped in the current repository.

## Robust Extension

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

Target for deterministic lane: $R_{\text{det}} \geq 0.999$.


## Scalarization Strategies (Multi-Objective to Single-Objective Reduction)

The canonical 6-objective formulation $J = w_1 T + w_2 S + w_3 M + w_4 B + w_5 R + w_6 E$ must be reduced to a scalar for CP-SAT / HiGHS. SynAPS supports two strategies:

### Hierarchical Weighted Sum (Default)

$$f = C_{\max} \cdot (1 + |S_{\text{ub}}| + |\ell_{\text{ub}}| + |T_{\text{ub}}|) + w_s \cdot \text{total\_setup} + w_\ell \cdot \text{total\_material} + w_T \cdot \text{total\_tardiness}$$

The multiplier $(1 + |S_{\text{ub}}| + \ldots)$ ensures **lexicographic dominance** of Makespan.

### $\varepsilon$-Constraint (Pareto Slice)

$$\min f_{\text{primary}} \quad \text{s.t.} \quad f_i \leq (1 + \varepsilon_i) \cdot f_i^* \quad \forall i \neq \text{primary}$$

Current shipped Pareto profiles use $\varepsilon = 0.10$ (10% relaxation).

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
| $|\mathcal{E}_o| = 1$ for all $o$ | Classical JSSP |
| Single machine per stage | Flow-shop |
| No precedence constraints | Parallel machine scheduling |
| $w_2 = \ldots = w_6 = 0$ | Single-objective tardiness minimization |
| $\sigma = 0$ | Setup-free FJSP |
| $\mathcal{R} = \emptyset$ | No auxiliary resource constraints |
