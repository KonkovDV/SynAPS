# Data Center Domain Guide

> **Scope**: GPU, VM, batch-compute, and maintenance scheduling under power, cooling, and SLA constraints.

<details><summary>🇷🇺 Краткое описание</summary>

Для ЦОД каноническая модель работает не хуже, чем для завода: job — это batch workload или migration wave, work center — GPU cluster, rack, node group или storage tier, setup — миграция контейнеров, прогрев кэша, смена образа, выделение сети. Ограничения задаются мощностью, охлаждением, affinity и SLA.
</details>

---

## 1. Domain Frame

Jobs are GPU training runs, inference batches, VM waves, storage compaction tasks, or maintenance operations. Work centers include compute clusters, racks, node groups, storage pools, and network domains.

## 2. SDST Mapping

| Canonical setup concept | Data center realization |
|-------------------------|-------------------------|
| State-to-state change | Workload image or tenant profile switch |
| Setup time | Container warm-up, VM migration, cache warming, data staging |
| Material loss | Lost reservation time, evicted cache, unused reserved capacity |
| Energy penalty | Peak power, cooling load spike, hot-aisle imbalance |

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Capacity available for immediate use |
| `processing` | Compute or maintenance task is running |
| `setup` | Boot, migration, image pull, or cache warm-up in progress |
| `blocked` | Waiting for capacity, network path, approval, or dependencies |
| `maintenance` | Planned node drain, firmware update, or hardware swap |

## 4. Setup Matrix Semantics

The setup matrix is driven by:

- workload type and image family
- data locality and storage tier
- GPU memory profile and model family
- tenant isolation or compliance zone
- rack affinity and cooling envelope

## 5. Auxiliary Resources

- power budget slots
- cooling headroom
- network bandwidth windows
- storage IOPS pools
- SRE or platform-engineer approval capacity

## 6. KPI Palette

- SLA attainment
- queue wait time
- energy cost and peak shaving
- GPU utilization and fragmentation
- migration success rate
- thermal or power cap breaches

## 7. Compliance and Regulatory Context

Typical governance surfaces:

- ISO 27001 / SOC 2 operations controls
- tenant isolation policies
- data residency rules
- service-level commitments by customer class

## 8. Example Parametrization

Reference schema example: [data_center.json](../../schema/examples/data_center.json)

Suggested `domain_attributes` fields:

- `workload_class`
- `gpu_profile`
- `power_kw`
- `cooling_tier`
- `latency_sla_ms`
- `data_residency_zone`
