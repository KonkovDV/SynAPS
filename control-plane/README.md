# SynAPS TypeScript Control Plane

Language: **EN** | [RU](README_RU.md)

This package is the minimal TypeScript BFF layer above the Python SynAPS kernel.

It does not implement operator UI, ERP/MES adapters, or long-lived workflow orchestration.
It proves a smaller but important boundary:

1. validate request payloads against the checked-in SynAPS JSON Schemas;
2. invoke the Python kernel through the stable contract CLI;
3. validate the Python response before returning it to callers.

## Endpoints

- `GET /healthz`
- `GET /metrics` (Prometheus exposition)
- `GET /openapi.json`
- `GET /api/v1/runtime-contract`
- `POST /api/v1/solve`
- `POST /api/v1/repair`
- `POST /api/v1/ui/gantt-model`

`GET /openapi.json` publishes an OpenAPI 3.1 document built from the checked-in SynAPS
runtime schemas.

`GET /api/v1/runtime-contract` remains the smaller index surface for schema filenames and
discoverability metadata, including the OpenAPI document path.

`POST /api/v1/ui/gantt-model` returns a read-only lane/bar projection (with precedence links
and delta overlays) so frontend Gantt viewers can render schedule vs baseline diff without
parsing solver internals.

## Observability + Guards

The control-plane now emits:

1. structured request/solver events (trace_id/span_id);
2. OpenTelemetry spans (when enabled);
3. RED-style Prometheus metrics under `/metrics`;
4. limit-guard fallback chain for solve requests.

Key env vars:

- `SYNAPS_OTEL_ENABLED=1`
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://.../v1/traces`
- `SYNAPS_ENABLE_LIMIT_GUARDS=1`
- `SYNAPS_LIMIT_GUARD_CHAIN=CPSAT-30,LBBD-10,RHC-ALNS,GREED`
- `SYNAPS_PYTHON_EXEC_TIMEOUT_MS=...`
- `SYNAPS_PYTHON_MAX_OUTPUT_BYTES=...`

Ready-to-import monitoring artifacts (Grafana dashboard + Prometheus alert rules):

- `../technical/monitoring/grafana/synaps-control-plane-slo.dashboard.json`
- `../technical/monitoring/prometheus/synaps-control-plane-alerts.yml`

## Local Commands

```bash
npm install
npm run test
npm run build
npm run dev
```

## Python Bridge

By default the control plane tries to locate a Python executable in this order:

1. `SYNAPS_PYTHON_BIN`
2. nearest ancestor `.venv`
3. `python` on Windows or `python3` on POSIX

The BFF executes:

```bash
python -m synaps solve-request <request.json>
python -m synaps repair-request <request.json>
```

## Boundary

This package is intentionally thin.

It is a transport and validation layer. It must not rebuild CP-SAT models or duplicate solver logic from the Python kernel.