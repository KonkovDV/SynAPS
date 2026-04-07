# 07 — Runtime Contract

> **Scope**: current verified invocation contract between a TypeScript control-plane edge and the Python SynAPS kernel.

<details><summary>🇷🇺 Краткое описание</summary>

SynAPS теперь имеет явный product/runtime contract на уровне JSON request/response schema и CLI/package entrypoints. Это не полноценный HTTP/gRPC API и не operator UI, но уже не просто research kernel без внешней точки входа. Контракт нужен, чтобы TypeScript control-plane мог работать с Python-ядром через стабильную, версионируемую границу.
</details>

---

## 1. What Exists Today

The current verified contract surface consists of:

1. request and response models in `synaps/contracts.py`;
2. generated JSON Schema artifacts in [`schema/contracts/`](../../schema/contracts/README.md);
3. package-level execution helpers for solve and repair requests;
4. CLI entrypoints for request-driven execution and schema export;
5. a minimal TypeScript BFF in [`control-plane/`](../../control-plane/README.md).

This is the current public proof of a bounded invocation surface.

---

## 2. Contract Files

| File | Purpose |
| --- | --- |
| [`solve-request.schema.json`](../../schema/contracts/solve-request.schema.json) | deterministic plan-generation request |
| [`solve-response.schema.json`](../../schema/contracts/solve-response.schema.json) | deterministic plan-generation response |
| [`repair-request.schema.json`](../../schema/contracts/repair-request.schema.json) | bounded repair request |
| [`repair-response.schema.json`](../../schema/contracts/repair-response.schema.json) | bounded repair response |

Regeneration command:

```bash
python -m synaps write-contract-schemas --output-dir schema/contracts
```

The schema files are generated from the Pydantic models in `synaps/contracts.py` and are intended to be consumed by a future TypeScript BFF or operator-facing control-plane.

---

## 3. Invocation Surfaces

### 3.1 Human-oriented surface

```bash
python -m synaps solve benchmark/instances/tiny_3x3.json
```

This remains the shortest manual entrypoint for routed portfolio execution.

### 3.2 Contract-oriented solve

```bash
python -m synaps solve-request path/to/solve-request.json
```

### 3.3 Contract-oriented repair

```bash
python -m synaps repair-request path/to/repair-request.json
```

### 3.4 Package entrypoints

- `execute_solve_request(...)`
- `execute_repair_request(...)`
- `solve_schedule(...)`
- `repair_schedule(...)`

### 3.5 Network-facing control plane

The current repo now includes a minimal TypeScript BFF package in [`control-plane/`](../../control-plane/README.md).

Current routes:

- `GET /healthz`
- `GET /api/v1/runtime-contract`
- `POST /api/v1/solve`
- `POST /api/v1/repair`

That package performs three tasks only:

1. validate inbound JSON against the checked-in contract schemas;
2. invoke the Python kernel via the contract CLI;
3. validate outbound JSON before returning it.

---

## 4. Design Rules

1. The deterministic kernel stays in Python.
2. TypeScript owns transport, sessions, auth, operator workflows, and integration adapters.
3. The contract must remain versioned and JSON-serializable.
4. Feasibility validation stays inside the Python kernel by default.
5. Natural-language explanation belongs above this layer, not inside the contract itself.

---

## 5. Current Guarantees

The current contract guarantees:

1. a stable request/response structure for solve and repair execution;
2. explicit routing context (`regime`, latency preference, exactness preference);
3. explicit portfolio provenance in `result.metadata["portfolio"]`;
4. explicit structural problem profiling in the response metadata;
5. optional but default-on feasibility verification for high-level portfolio execution.

---

## 6. What It Does Not Yet Claim

This page does **not** claim that SynAPS already ships:

1. a production deployment architecture for that BFF;
2. a gRPC service boundary;
3. operator UI workflows;
4. ERP/MES production adapters;
5. multi-tenant runtime packaging.

Those remain next-stage productization work.

---

## 7. Recommended TypeScript Consumption Pattern

```text
TypeScript BFF
  → validate payload with Ajv/Zod against schema/contracts/*.json
  → invoke Python kernel through one bounded surface
  → validate response against response schema
  → publish to WebSocket / REST / event bus
```

The control-plane should not reconstruct CP-SAT models in TypeScript. It should own orchestration and transport, not the combinatorial kernel.

---


### Example Request/Response Payloads

**Solve Request:**
```json
{
  "problem": {
    "orders": [{"id": "O1", "priority": 500, "due_date": 1440}],
    "operations": [
      {"id": "op1", "order_id": "O1", "seq_in_order": 1, "state_id": "S1",
       "base_duration_min": 60, "eligible_wc_ids": ["WC1", "WC2"]}
    ],
    "work_centers": [
      {"id": "WC1", "code": "LATHE-01", "speed_factor": 1.0, "max_parallel": 1}
    ],
    "setup_entries": [
      {"work_center_id": "WC1", "from_state_id": "S1", "to_state_id": "S2",
       "setup_minutes": 30, "material_loss": 0.5, "energy_kwh": 2.0}
    ],
    "horizon_start": 0,
    "horizon_end": 2880
  },
  "solver_config": "CPSAT-10",
  "request_id": "req-2026-04-07-001"
}
```

**Solve Response:**
```json
{
  "solver_name": "CPSAT-10",
  "status": "OPTIMAL",
  "assignments": [
    {"operation_id": "op1", "work_center_id": "WC1",
     "start_offset": 0, "end_offset": 60, "setup_minutes": 0}
  ],
  "objective": {
    "makespan": 60.0,
    "total_setup_minutes": 0.0,
    "total_material_loss": 0.0,
    "total_tardiness": 0.0,
    "weighted_sum": 60.0
  },
  "duration_ms": 26,
  "metadata": {"portfolio": "CPSAT-10", "gap": 0.0}
}
```

### Error Contract

All BFF errors follow a consistent envelope:
```json
{
  "error": "SynapsPythonBridgeError",
  "message": "Solver returned INFEASIBLE: precedence cycle detected",
  "request_id": "req-2026-04-07-001",
  "status_code": 422
}
```

HTTP status codes: `200` (success), `400` (invalid input, AJV rejection), `422` (infeasible/solver error), `502` (Python bridge failure), `504` (solver timeout).


## 8. Verification Surface

The runtime contract is covered by:

1. contract execution tests;
2. CLI tests;
3. portfolio and repair orchestration tests;
4. generated-schema tests.

This gives a real proof surface for the language boundary described in [06_LANGUAGE_AND_RUNTIME_STRATEGY.md](06_LANGUAGE_AND_RUNTIME_STRATEGY.md).