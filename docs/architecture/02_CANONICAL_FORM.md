# Canonical Mathematical Form

<details>
<summary>🇷🇺 Каноническая математическая форма</summary>

Формальная спецификация задачи планирования Syn-APS: MO-FJSP-SDST-ML-ARC. Описаны множества, переменные, ограничения, целевая функция и робастное расширение.

</details>

## Problem Class

**MO-FJSP-SDST-ML-ARC** — Multi-Objective Flexible Job-Shop Scheduling Problem with Sequence-Dependent Setup Times, Machine Learning advisory, and Auxiliary Resource Constraints.

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

**Supply ≤ Demand (auxiliary resources):**

$$\forall r \in \mathcal{R},\; \forall t \in \mathcal{T}: \quad \sum_{o \,:\, r \in \text{req}(o),\; s_o \leq t < s_o + p_{o}} 1 \;\leq\; \text{cap}(r, t)$$

**Precedence:**

$$\forall j \in \mathcal{J},\; \forall (o_i, o_{i+1}) \in \mathcal{O}_j: \quad s_{o_{i+1}} \;\geq\; s_{o_i} + p_{o_i}$$

**No-overlap (with setup):**

$$\forall m,\; \forall (o_a, o_b) \text{ consecutive on } m: \quad s_{o_b} \;\geq\; s_{o_a} + p_{o_a} + \sigma(o_a, o_b, m)$$

where $\sigma(o_a, o_b, m)$ is the sequence-dependent setup time.

**Capacity:**

$$\forall m \in \mathcal{M},\; \forall t: \quad \sum_{o: x_{om}=1,\; s_o \leq t < s_o + p_o} 1 \;\leq\; \text{cap}(m)$$

## Objective Function

$$J = w_1 T + w_2 S + w_3 M + w_4 B + w_5 R + w_6 E$$

| Term | Formula | Description |
|------|---------|-------------|
| $T$ | $\sum_{j} \alpha_j \max(0,\, C_j - d_j)$ | Weighted tardiness |
| $S$ | $\sum_{m} \sum_{\text{consecutive } (a,b)} \sigma(a, b, m)$ | Total setup time |
| $M$ | $\sum_{o} \text{material\_cost}(o)$ | Material waste / auxiliary resource cost |
| $B$ | $\text{Var}(\text{load}_m)$ or $\max(\text{load}_m) - \min(\text{load}_m)$ | Load imbalance |
| $R$ | $\|A_{\text{new}} \triangle A_{\text{old}}\| / \|A_{\text{old}}\|$ | Schedule stability |
| $E$ | $\sum_{m,t} \text{tariff}(t) \cdot \text{power}(m, t)$ | Energy cost |

**Weights** $w_1, \ldots, w_6$ are configurable per policy profile and can be tuned by ML advisory or operator override.

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

## Special Cases

| If you restrict... | You get... |
|--------------------|-----------|
| $|\mathcal{E}_o| = 1$ for all $o$ | Classical JSSP |
| Single machine per stage | Flow-shop |
| No precedence constraints | Parallel machine scheduling |
| $w_2 = \ldots = w_6 = 0$ | Single-objective tardiness minimization |
| $\sigma = 0$ | Setup-free FJSP |
| $\mathcal{R} = \emptyset$ | No auxiliary resource constraints |
