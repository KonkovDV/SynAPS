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
3. RED-style Prometheus metrics under `/metrics` (duration, solver outcomes, limit-guard transitions, bridge errors, feasibility kinds, gap/windows);
4. limit-guard fallback chain for solve requests.

Key env vars:

- `SYNAPS_OTEL_ENABLED=1`
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://.../v1/traces`
- `SYNAPS_ENABLE_LIMIT_GUARDS=1`
- `SYNAPS_LIMIT_GUARD_CHAIN=CPSAT-30,LBBD-10,RHC-ALNS,GREED`
- `SYNAPS_CONTROL_PLANE_API_KEY=...`
- `SYNAPS_CONTROL_PLANE_MAX_BODY_BYTES=10000000`
- `SYNAPS_CONTROL_PLANE_RATE_LIMIT_MAX=60`
- `SYNAPS_CONTROL_PLANE_RATE_LIMIT_WINDOW_MS=60000`
- `SYNAPS_PYTHON_EXEC_TIMEOUT_MS=...`
- `SYNAPS_PYTHON_MAX_OUTPUT_BYTES=...`

When `SYNAPS_CONTROL_PLANE_API_KEY` is set, the control plane requires either
`x-api-key: <value>` or `Authorization: Bearer <value>` on every route.
Optional fixed-window throttling is enabled by setting both
`SYNAPS_CONTROL_PLANE_RATE_LIMIT_MAX` and `SYNAPS_CONTROL_PLANE_RATE_LIMIT_WINDOW_MS`.

Ready-to-import monitoring artifacts (Grafana dashboard + Prometheus alert rules):

- `../technical/monitoring/grafana/synaps-control-plane-slo.dashboard.json`
- `../technical/monitoring/prometheus/synaps-control-plane-alerts.yml`

## Local Setup

This package is not a standalone Node service. `npm test`, `npm run dev`, and the live
solve/repair routes shell out into the Python `synaps` CLI, so the repository-level
Python package must be installed into the interpreter that the bridge will use.

```bash
cd ..
python -m pip install -e ".[dev]"
cd control-plane
npm install
npm run test
npm run build
npm run dev
```

The GitHub Actions `control-plane` job follows the same bootstrap order: set up Python,
install SynAPS with `pip install -e ".[dev]"`, then run the Node test/build steps.

## Python Bridge

By default the control plane tries to locate a Python executable in this order:

1. `SYNAPS_PYTHON_BIN`
2. nearest ancestor `.venv`
3. `python` on Windows or `python3` on POSIX

Set `SYNAPS_PYTHON_BIN` explicitly when CI or local tooling should use a specific
interpreter instead of the nearest ancestor virtual environment.

The Python bridge now forwards only the minimal runtime environment it needs:
system path/process variables, `SYNAPS_PYTHON_*`, `SYNAPS_DISABLE_NATIVE_ACCELERATION`,
and `OTEL_*`. Control-plane-only settings such as `SYNAPS_CONTROL_PLANE_API_KEY`
and rate-limit/body-limit knobs are intentionally not propagated to the Python subprocess.

The BFF executes:

```bash
python -m synaps solve-request <request.json>
python -m synaps repair-request <request.json>
```

For solve requests, the bridge now also passes `--instance-dir <repo-root>` so callers can
send `problem_instance_ref` instead of embedding very large scheduling instances inline.
That file-backed path can pair `problem_instance_ref` with `problem_slice` to materialize an
order-complete subset before the Python contract validates `ScheduleProblem`, which keeps
300K/500K study flows off the JSON/Pydantic payload boundary.

When callers need coverage-oriented runtime behavior rather than the default balanced router,
set `context.portfolio_policy = "feasibility-first"`. The control plane validates and forwards
that policy unchanged, and the Python router then biases nominal non-exact flows toward
feasible-coverage portfolio members instead of exactness-heavy defaults.

## Boundary

This package is intentionally thin.

It is a transport and validation layer. It must not rebuild CP-SAT models or duplicate solver logic from the Python kernel.