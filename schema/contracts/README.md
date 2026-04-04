# Runtime Contract Schemas

This directory contains the current public JSON Schema bundle for the SynAPS
runtime invocation contract.

## Files

- `solve-request.schema.json` — request contract for deterministic plan generation
- `solve-response.schema.json` — response contract for deterministic plan generation
- `repair-request.schema.json` — request contract for bounded repair execution
- `repair-response.schema.json` — response contract for bounded repair execution

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

## Boundary

These schemas define the invocation contract. They do not, by themselves,
mandate HTTP, gRPC, NATS, or any specific deployment topology.