# 06 — Language & Runtime Strategy

> **Scope**: Polyglot execution boundaries for SynAPS from operator edge to solver kernel.

<details><summary>🇷🇺 Краткое описание</summary>

SynAPS не должен выбирать один язык «для всего». Правильная архитектура — полиглотная: TypeScript на внешнем контуре и UI, Python для CP-SAT/ML/DES-оркестрации, Rust для горячих вычислительных путей. Это документ о границах и ответственности языков, а не заявление о том, что все эти рантаймы уже реализованы в текущем репозитории.
</details>

---

## 1. Core Rule

Language choice in SynAPS follows **hot path, ecosystem fit, and runtime boundary**, not team habit.

Four rules dominate:

1. Use the strongest ecosystem for the specific layer.
2. Keep number-crunching kernels separate from UI and integration code.
3. Keep business policy and plant rules outside solver code whenever they can be expressed declaratively.
4. Prefer explicit contracts between runtimes over accidental in-process coupling.

---

## 2. Current Proof Surface vs Target Runtime Split

### Current proof surface

The repository currently proves:

1. a Python scheduling kernel;
2. baseline solvers and bounded repair;
3. benchmark harness and feasibility checking;
4. research and architecture documentation.

### Target runtime split

The target SynAPS platform is intentionally polyglot:

1. **TypeScript** on the control-plane edge and operator-facing surfaces;
2. **Python** for exact optimization orchestration, ML advisory, and simulation-heavy research surfaces;
3. **Rust** for hot-path heuristics, feasibility kernels, and future metaheuristic workers.

Important boundary:

This is a **target architecture document**, not a claim that all three runtime layers are already implemented in the current repository.

---

## 3. Placement Matrix

| Concern | Preferred language / runtime | Why | Avoid |
| --- | --- | --- | --- |
| Operator UI | TypeScript + React | shared contracts, fast iteration, browser-native integration | solver math in browser code |
| Control-plane API / BFF | TypeScript on Node.js or Bun | API contracts, auth/session surfaces, WebSocket delivery, ERP/MES-facing orchestration | CP-SAT model construction in gateway code |
| Exact optimization orchestration | Python | strongest OR-Tools and scientific stack, fast model iteration, direct ML interop | treating Python as the best place for every hot loop |
| ML advisory and XAI services | Python | PyTorch, PyG, ONNX, data tooling, experiment velocity | mixing LLM output into the deterministic feasibility path |
| Hot-path heuristics | Rust | predictable latency, native concurrency, no GC pauses, strong fit for tight combinatorial loops | rewriting every non-hot-path service in Rust prematurely |
| Feasibility checker and repair kernels | Rust (target) with Python parity surface | deterministic validation path, reusable native core | duplicating business policy inside low-level kernels |
| Plant rules / policy | declarative models such as JDM/JSON rules, Rego, SQL/JSON Schema | keeps policy editable and auditable outside solver code | hardcoding plant exceptions into ATCS or CP-SAT logic |

---

## 4. Python Boundary

Python remains the canonical proof surface for the solver and ML stack.

It is the right home for:

1. CP-SAT and HiGHS model building and orchestration;
2. ML training, replay, and inference pipelines;
3. scheduling experiments, benchmark harnesses, and simulation-heavy work;
4. data validation, normalization, and XAI preprocessing.

### Free-threading boundary

Python 3.13 free-threaded builds are promising, but they are **not yet a blanket architecture guarantee**.

Official Python guidance currently states:

1. free-threaded CPython is still experimental;
2. some C extensions may re-enable the GIL;
3. there is still measurable single-thread overhead.

Operational rule:

1. baseline SynAPS correctness must hold on standard CPython;
2. free-threaded Python should be treated as an opt-in acceleration lane, benchmarked per dependency set;
3. solver performance promises must not rely on no-GIL language alone.

---

## 5. Rust Boundary

Rust is the preferred target for the computational hot path once profiling proves the need.

### Current proof surface (v0.3.0)

The `synaps_native` PyO3 extension implements:

1. **ATCS scoring**: scalar and batch (rayon-parallel) variants;
2. **RHC candidate metrics**: Vec, zero-copy NumPy+CSR, and CSR-in-Rust (jagged) paths;
3. **Resource capacity feasibility**: sweep-line algorithm.

Silicon-level optimizations verified on Intel i5-13600KF (Raptor Lake):
- Branchless overdue boost (eliminates branch misprediction on P/E hybrid);
- Rayon work-stealing tuned for P/E core asymmetry (`with_min_len(256)`);
- `target-cpu=native` enables AVX2/FMA3 auto-vectorization;
- **No AVX-512**: hardware-disabled on 12th–14th Gen hybrid architectures.

See: [08_HPC_SILICON_OPTIMIZATION_ROADMAP.md](08_HPC_SILICON_OPTIMIZATION_ROADMAP.md) for the full hardware-aware optimization roadmap.

### Target candidates

1. GREED / ATCS scoring loops;
2. feasibility checking over large neighborhoods;
3. ALNS destroy/repair operators;
4. non-dominated sorting, crowding distance, and neighborhood evaluation in future metaheuristics;
5. rule-engine bindings or native execution surfaces where latency matters.

Migration rule:

1. do not port by ideology;
2. port after a replay corpus or benchmark identifies a stable bottleneck;
3. keep the Rust interface narrow and contract-first.

Preferred early integration path:

1. expose Rust kernels to Python through PyO3/maturin when in-process latency matters;
2. extract them into independent services only when isolation or separate scaling is justified.

---

## 6. TypeScript Boundary

TypeScript is the preferred language for the external application shell.

It should own:

1. operator-facing UI;
2. session-oriented APIs and WebSockets;
3. authn/authz-adjacent application flows;
4. anti-corruption adapters at the ERP/MES boundary when the concern is contract translation and IO, not heavy optimization.

It should **not** own:

1. CP-SAT model construction;
2. local search kernels;
3. feasibility-critical optimization logic;
4. research-heavy ML pipelines.

---

## 7. Runtime Contracts Between Languages

| Boundary | Recommended contract | Notes |
| --- | --- | --- |
| TypeScript → Python | OpenAPI / JSON Schema, NATS events, or gRPC | best for control-plane to optimizer service invocation |
| TypeScript → Rust | gRPC / HTTP only when Rust is extracted as a service | avoid direct UI-to-native coupling |
| Python → Rust | PyO3 / maturin first, gRPC second | in-process native acceleration before service explosion |
| Rules / Policy → Solvers | JSON/JDM, Rego, SQL-backed policy tables | keeps plant-specific logic editable and auditable |

Contract rule:

The deterministic kernel returns structured results and provenance. Natural-language explanation belongs to the XAI / LLM layer above it.

### Current verified proof surface

As of April 2026, the currently verified TypeScript → Python boundary is the bounded JSON invocation contract exposed by:

1. `synaps/contracts.py`;
2. `schema/contracts/*.schema.json`;
3. `python -m synaps solve-request ...` and `python -m synaps repair-request ...`.

This is a contract surface, not yet a claim of full HTTP/gRPC productization.

---

## 8. Zero-Touch Edge Implication

Industrial productization pushes SynAPS toward a zero-touch operating model:

1. immutable or tightly controlled node images;
2. declarative rollout and rollback;
3. API-driven management rather than manual shell mutation;
4. solver workers treated as replaceable cattle, not hand-tuned pets.

This document does **not** claim that the current repository already ships that full edge stack.

It only states that the language split above is compatible with that operating model.

---

## 9. Near-Term Roadmap

1. Keep Python as the canonical proof and research surface.
2. Freeze narrow solver contracts before any native-port wave.
3. Benchmark hot loops with realistic replay corpora before moving them to Rust.
4. Introduce TypeScript control-plane surfaces only alongside real product/runtime contracts.
5. Keep business rules declarative instead of embedding plant exceptions deep in solver code.

---

## 10. Anti-Patterns

1. Building CP-SAT models in TypeScript just to keep a single-language stack.
2. Treating Python free-threading as already-settled production infrastructure.
3. Hardcoding plant policy into heuristics or exact solver code.
4. Extracting microservices before product/runtime boundaries exist.
5. Letting LLM or ML advisory outputs bypass the deterministic feasibility gate.