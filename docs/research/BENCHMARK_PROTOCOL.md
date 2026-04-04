# Benchmark Protocol — SynAPS

> **Purpose**: Standardized methodology for evaluating solver quality, runtime performance, and scalability of the SynAPS scheduling engine across multiple domains.

<details><summary>🇷🇺 Краткое описание</summary>

Протокол бенчмаркинга SynAPS: формат входных данных, стандартные наборы задач (Brandimarte Mk01–Mk10, Kacem, Fattahi), определения KPI, методология сравнения с базовыми решениями, статистическая валидность (30 запусков, медиана, IQR), и формат отчёта.
</details>

---

## 1. Instance Format

All benchmark instances use the SynAPS JSON schema (see [`schema/README.md`](../../schema/README.md)).

### Minimal Instance Fields

```json
{
  "instance_id": "bench_tiny_3x3",
  "metadata": {
    "source": "synthetic",
    "domain": "generic",
    "n_jobs": 3,
    "n_machines": 3,
    "n_operations": 9,
    "has_sdst": true,
    "has_aux_resources": false
  },
  "orders": [ ... ],
  "work_centers": [ ... ],
  "setup_matrix": [ ... ]
}
```

### Size Classes

| Class | Jobs | Machines | Operations | SDST | Aux Resources | Use Case |
|-------|------|----------|------------|------|----------------|----------|
| **Tiny** | 3 | 3 | 9–15 | Optional | No | Unit test, CI smoke |
| **Small** | 10 | 5 | 30–60 | Yes | No | Algorithm regression |
| **Medium** | 20 | 10 | 100–250 | Yes | Optional | Solver comparison |
| **Large** | 50 | 20 | 500–1500 | Yes | Yes | Scalability test |
| **Industrial** | 200+ | 50+ | 5000+ | Yes | Yes | Production realism |

---

## 2. Standard Datasets

### 2.1 Classical FJSP Benchmarks

These benchmarks are converted to SynAPS JSON format. Converters live in `benchmark/converters/`.

| Dataset | Source | Instances | Jobs × Machines | Characteristics |
|---------|--------|-----------|-----------------|-----------------|
| **Brandimarte** | Brandimarte (1993) | Mk01–Mk10 | 10×6 → 20×15 | Classical FJSP, no SDST |
| **Kacem** | Kacem et al. (2002) | 4 instances | 4×5 → 15×10 | Multi-objective FJSP |
| **Fattahi** | Fattahi et al. (2007) | SFJS01–SFJS10, MFJS01–MFJS10 | 2×2 → 20×10 | FJSP with partial flexibility |
| **HU** | Hurink et al. (1994) | edata/rdata/vdata | Various | JSP with FJSP extensions |

### 2.2 SynAPS Synthetic Instances

Generated via parametric instance generator (`benchmark/generate_instances.py`, planned).

| Instance | Size | SDST | Aux | Domain | Purpose |
|----------|------|------|-----|--------|---------|
| `tiny_3x3.json` | 3×3 | ✓ | ✗ | generic | Smoke test |
| `medium_20x10.json` | 20×10 | ✓ | ✓ | metallurgy | Regression |
| `large_50x20.json` | 50×20 | ✓ | ✓ | pharma | Scalability |
| `industrial_200x50.json` | 200×50 | ✓ | ✓ | electronics | Stress test |

---

## 3. KPI Definitions

### 3.1 Primary Objectives

| KPI | Symbol | Formula | Unit | Direction |
|-----|--------|---------|------|-----------|
| Makespan | $C_{\max}$ | $\max_j C_j$ | seconds | minimize |
| Total Weighted Tardiness | $T_w$ | $\sum_j w_j \max(0, C_j - d_j)$ | weighted seconds | minimize |
| Total Setup Time | $S$ | $\sum_{m} \sum_{(i,j) \in \sigma_m} s_{ij}^m$ | seconds | minimize |
| Machine Utilization | $U$ | $\frac{\sum_m \text{busy}_m}{|M| \cdot C_{\max}}$ | ratio [0,1] | maximize |

### 3.2 Robustness Metrics

| KPI | Symbol | Formula | Description |
|-----|--------|---------|-------------|
| CVaR-α | $\text{CVaR}_\alpha$ | $\mathbb{E}[C_{\max} \mid C_{\max} \geq \text{VaR}_\alpha]$ | Conditional tail makespan at α=0.95 |
| Schedule Stability | $\Delta$ | $\frac{\|\sigma' - \sigma\|_1}{n}$ | L1 distance between pre/post-disruption schedules |

### 3.3 Solver Performance Metrics

| KPI | Description | Unit |
|-----|-------------|------|
| **Wall-clock time** | Total solve time (including model build) | milliseconds |
| **Optimality gap** | $(UB - LB) / LB \times 100$ where known | percent |
| **Feasibility rate** | Fraction of runs producing a feasible schedule | ratio [0,1] |
| **Solution quality ratio** | $C_{\max}^{\text{solver}} / C_{\max}^{\text{best\_known}}$ | ratio ≥ 1.0 |

---

## 4. Evaluation Methodology

### 4.1 Solver Configurations Under Test

| Config | Solver Stack | Timeout | Use Case |
|--------|-------------|---------|----------|
| `GREED` | ATCS dispatch heuristic | 1 s | Baseline, real-time |
| `CPSAT-10` | CP-SAT with 10 s timeout | 10 s | Quick exact |
| `CPSAT-60` | CP-SAT with 60 s timeout | 60 s | Full exact |
| `LBBD` | HiGHS master + CP-SAT sub | 120 s | Large-scale decomposition |
| `HGAT+CPSAT` | GNN weight prediction → CP-SAT | 15 s | ML-guided exact |
| `RL-DISPATCH` | TorchRL learned dispatch policy | 1 s | RL alternative to GREED |

### 4.2 Statistical Rigor

- **Runs per configuration**: 30 (for stochastic solvers; 1 for deterministic)
- **Reported statistics**: median, mean, IQR (Q1–Q3), min, max
- **Hardware normalization**: All times reported relative to a reference machine spec
- **Randomization**: Different random seeds for each run; seeds logged for reproducibility
- **Timeout handling**: If solver times out, report the incumbent solution quality + flag `TIMEOUT`

### 4.3 Comparison Baselines

| Baseline | Description |
|----------|-------------|
| **SPT** | Shortest Processing Time — classic priority rule |
| **EDD** | Earliest Due Date — classic priority rule |
| **ATCS** | Apparent Tardiness Cost with Setups (SynAPS GREED) |
| **BKS** | Best Known Solution from literature (when available) |
| **Random** | Uniform random feasible assignment (lower bound sanity) |

### 4.4 Multi-Objective Evaluation

For multi-objective runs (NSGA-III):

| Metric | Description |
|--------|-------------|
| **Hypervolume (HV)** | Volume dominated by the Pareto front, relative to a reference point |
| **IGD** | Inverted Generational Distance to true Pareto front (if known) |
| **Spread (Δ)** | Diversity measure across the Pareto front |
| **Pareto set size** | Number of non-dominated solutions returned |

---

## 5. Instance Generation Protocol

For synthetic instances beyond classical benchmarks:

```python
# Parametric generation (pseudocode)
def generate_instance(
    n_jobs: int,
    n_machines: int,
    n_ops_per_job: tuple[int, int],  # (min, max) operations per job
    flexibility: float,               # fraction of machines eligible per op (0.3–1.0)
    sdst_density: float,              # fraction of machine pairs with non-zero setup
    sdst_range: tuple[int, int],      # (min, max) setup time
    proc_time_range: tuple[int, int], # (min, max) processing time
    due_date_tightness: float,        # τ ∈ [0.2, 0.8]
    aux_resource_prob: float,         # probability an op needs auxiliary resource
    seed: int,
) -> dict:
    ...
```

Parameters chosen to cover the difficulty spectrum: tight due dates (τ=0.3), loose due dates (τ=0.7), low flexibility (0.3), full flexibility (1.0).

---

## 6. Report Format

Each benchmark run produces a structured JSON report:

```json
{
  "benchmark_id": "run_2026_04_01_001",
  "timestamp": "2026-04-01T14:30:00Z",
  "hardware": {
    "cpu": "AMD EPYC 9654 96-Core",
    "ram_gb": 256,
    "gpu": "NVIDIA A100 80GB",
    "os": "Ubuntu 24.04"
  },
  "instance": "medium_20x10.json",
  "solver_config": "CPSAT-60",
  "results": {
    "makespan": 1847,
    "weighted_tardiness": 342.5,
    "total_setup_time": 210,
    "utilization": 0.87,
    "wall_clock_ms": 14523,
    "gap_percent": 2.1,
    "feasible": true,
    "timeout": false
  },
  "statistics": {
    "runs": 30,
    "median_makespan": 1847,
    "mean_makespan": 1862.3,
    "iqr_makespan": [1835, 1889],
    "min_makespan": 1812,
    "max_makespan": 1934
  }
}
```

---

## 7. CI Integration

Benchmark runs are automated via GitHub Actions (see [`.github/workflows/benchmark.yml`](../../.github/workflows/benchmark.yml)):

| Trigger | Instances | Timeout | Purpose |
|---------|-----------|---------|---------|
| Every push (CI) | `tiny_3x3.json` only | 30 s | Smoke test — solver doesn't crash |
| Weekly schedule | All small + medium | 5 min total | Regression detection |
| Manual dispatch | All sizes | 30 min | Full performance evaluation |

### Regression Detection

A benchmark regression is flagged when:
- Makespan increases > 5% vs. last weekly run on the same instance
- Wall-clock time increases > 20% on the same hardware
- Feasibility rate drops below 1.0 on previously feasible instances

---

## 8. Reproducing Results

```bash
# Install
pip install -e ".[dev]"

# Run tiny smoke test
python benchmark/run_benchmark.py --instance benchmark/instances/tiny_3x3.json --solver GREED

# Run full medium benchmark (30 runs)
python benchmark/run_benchmark.py \
  --instance benchmark/instances/medium_20x10.json \
  --solver CPSAT-60 \
  --runs 30 \
  --output benchmark/results/

# Compare solvers
python benchmark/run_benchmark.py \
  --instance benchmark/instances/medium_20x10.json \
  --solver GREED CPSAT-10 CPSAT-60 \
  --runs 30 \
  --compare
```

---

*Protocol version 1.0 — 2026-04.*
