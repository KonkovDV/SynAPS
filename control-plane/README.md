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
- `GET /openapi.json`
- `GET /api/v1/runtime-contract`
- `POST /api/v1/solve`
- `POST /api/v1/repair`

`GET /openapi.json` publishes an OpenAPI 3.1 document built from the checked-in SynAPS
runtime schemas.

`GET /api/v1/runtime-contract` remains the smaller index surface for schema filenames and
discoverability metadata, including the OpenAPI document path.

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