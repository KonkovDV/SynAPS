# Runtime Contract Schemas

This directory contains the current public JSON Schema bundle for the SynAPS
runtime invocation contract.

## Files

- `solve-request.schema.json` — request contract for deterministic plan generation
- `solve-response.schema.json` — response contract for deterministic plan generation
- `repair-request.schema.json` — request contract for bounded repair execution
- `repair-response.schema.json` — response contract for bounded repair execution
- `examples/solve-request.example.json` — minimal end-to-end solve request payload
- `examples/solve-request.instance-ref.example.json` — file-backed solve request with pre-validation slicing
- `examples/solve-response.example.json` — corresponding solve response payload
- `examples/repair-request.example.json` — minimal end-to-end repair request payload
- `examples/repair-response.example.json` — corresponding repair response payload

## Regeneration

These files are generated from the Pydantic contract models in
`synaps/contracts.py`.

```bash
python -m synaps write-contract-schemas --output-dir schema/contracts
```

## Intended Consumer

The primary consumer is the future TypeScript control-plane / BFF layer.

Recommended flow:

1. validate inbound payloads against these schemas;
2. invoke the Python kernel via `python -m synaps solve-request` or `python -m synaps repair-request`;
3. validate outbound payloads against the corresponding response schema;
4. keep network transport concerns outside the deterministic kernel.

`SolveRequest` now supports two mutually exclusive problem sources:

- inline `problem` for small and medium payloads;
- relative `problem_instance_ref` for file-backed execution, optionally paired with
	`problem_slice` so order-complete subsets can be materialized before Pydantic enforces
	the `MAX_SCHEDULE_OPERATIONS` ceiling.

When `problem_instance_ref` is used, resolve it against an explicit instance root:

```bash
python -m synaps solve-request request.json --instance-dir .
```

You can start from the `examples/` payloads for smoke tests and external integration
prototypes.

## Boundary

These schemas define the invocation contract. They do not, by themselves,
mandate HTTP, gRPC, NATS, or any specific deployment topology.