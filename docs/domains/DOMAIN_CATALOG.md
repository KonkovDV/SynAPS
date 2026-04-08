# Domain Catalog — SynAPS Universal Applicability

> **Purpose**: Master index of industry domains where the MO-FJSP-SDST-ARC canonical form applies. Each domain maps the canonical APS model to its specific vocabulary, constraints, KPIs, and compliance requirements.

<details><summary>🇷🇺 Краткое описание</summary>

Каталог отраслевых доменов SynAPS. Каждый домен описывает маппинг канонической модели FJSP на специфику отрасли: словарь состояний (state dictionary), семантику матрицы переналадок, вспомогательные ресурсы, палитру KPI, нормативные требования. 8 доменов: металлургия, фармацевтика, электроника, ЦОД, энергетика, пищевая промышленность, логистика, аэрокосмос.
</details>

---

## How to Read Domain Guides

Each domain guide follows a uniform structure:

| Section | Content |
|---------|---------|
| **SDST Mapping** | What "setup" means physically in this domain |
| **State Dictionary** | Machine/work-center states (idle, processing, setup, maintenance, etc.) |
| **Setup Matrix Semantics** | What drives $s_{ij}^m$ values (e.g., alloy grade change, cleanroom class, thermal ramp) |
| **Auxiliary Resources** | Shared resources beyond machines (tooling, personnel, utilities, cranes) |
| **KPI Palette** | Domain-specific objectives beyond $C_{\max}$ and $T_w$ |
| **Compliance & Regulatory** | Industry-specific standards (GMP, ISO, IATF, etc.) |
| **Example Schema** | Link to `schema/examples/<domain>.json` |

---

## Domain Matrix

| # | Domain | Guide | Example Schema | Primary SDST Driver | Unique Constraint |
|---|--------|-------|---------------|---------------------|-------------------|
| 1 | [Metallurgy](metallurgy.md) | ✅ | [`metallurgy.json`](../../schema/examples/metallurgy.json) | Alloy grade changeover | Furnace thermal inertia, crane sharing |
| 2 | [Pharmaceutical](pharmaceutical.md) | ✅ | [`pharmaceutical.json`](../../schema/examples/pharmaceutical.json) | Product/allergen changeover | GMP cleanroom class, batch traceability |
| 3 | [Electronics](electronics.md) | ✅ | [`electronics.json`](../../schema/examples/electronics.json) | Component family switch | Pick-and-place nozzle change, AOI calibration |
| 4 | [Data Center](data_center.md) | ✅ | [`data_center.json`](../../schema/examples/data_center.json) | VM/container migration | Power/cooling capacity, rack affinity |
| 5 | [Energy](energy.md) | ✅ | — | Fuel type / turbine ramp | Grid demand curve, emission cap |
| 6 | [Food & Beverage](food_beverage.md) | ✅ | [`food_beverage.json`](../../schema/examples/food_beverage.json) | Flavor/allergen changeover | HACCP CCP gates, shelf-life window |
| 7 | [Logistics](logistics.md) | ✅ | — | Vehicle/route reconfiguration | Time-window constraints, vehicle capacity |
| 8 | [Aerospace](aerospace.md) | ✅ | — | Material/coating change | AS9100 traceability, NDT hold points |

---

## Universal Mapping Pattern

Every domain maps to the canonical model via:

$$\text{Domain-specific process} \xrightarrow{\text{adapter}} \text{MO-FJSP-SDST-ARC}$$

| Canonical Concept | Domain Realization (varies) |
|-------------------|-----------------------------|
| **Job** ($J_j$) | Production order, batch, work order, service request |
| **Operation** ($O_{jk}$) | Processing step, stage, task, phase |
| **Work Center** ($M_m$) | Machine, reactor, furnace, server rack, turbine |
| **Setup Time** ($s_{ij}^m$) | Changeover, cleaning, calibration, thermal ramp |
| **Auxiliary Resource** ($R_r$) | Crane, operator, tool, utility, cleanroom slot |
| **Due Date** ($d_j$) | Customer delivery, batch expiry, SLA deadline |
| **Weight** ($w_j$) | Priority class, customer tier, penalty cost |

---

## Adding a New Domain

1. Create `docs/domains/<domain_name>.md` following the template structure
2. Add a JSON example to `schema/examples/<domain_name>.json`
3. Register in this catalog table
4. Open a PR using the [Domain Request](../../.github/ISSUE_TEMPLATE/domain_request.md) template

---

*8 domains documented. Catalog version 1.0 — 2026-04.*
