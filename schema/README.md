# Schema Package

> SQL DDL for PostgreSQL 18+ and JSON domain parametrization examples.

## Structure

```
schema/
├── ddl/
│   ├── 001_core_tables.sql        -- states, orders, operations, work_centers
│   ├── 002_setup_matrix.sql       -- SDST graph
│   ├── 003_auxiliary_resources.sql -- auxiliary resources & requirements
│   ├── 004_scheduling.sql         -- schedule_runs, assignments, overrides
│   └── 005_indexes.sql            -- all secondary indexes
└── examples/
    ├── metallurgy.json            -- alloy grades, furnace purges
    ├── pharmaceutical.json        -- GxP, CIP-SIP protocols
    ├── electronics.json           -- SMT, reflow profiles
    ├── data_center.json           -- GPU workloads, power budgets
    └── food_beverage.json         -- allergens, HACCP
```

## Usage

```bash
# Apply all DDL in order
for f in schema/ddl/*.sql; do
  psql -d synaps -f "$f"
done

# Load example domain data
# (examples are parametrization references, not loadable fixtures)
```

## Notes

- All tables use `UUID` primary keys via `gen_random_uuid()`.
- `domain_attributes JSONB` fields accept any valid JSON; validate at the application layer.
- Indexes cover the most common query patterns; add GIN indexes on `domain_attributes` if JSONB containment queries (`@>`) are frequent.
- DDL is idempotent-safe when wrapped in transactions with `IF NOT EXISTS` guards (add as needed for your migration tool).
