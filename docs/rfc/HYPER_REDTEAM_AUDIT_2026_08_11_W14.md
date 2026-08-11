# Literature + Hyper Red Team Wave 14 (2026-08-11)

Lit anchors: EJOR 329 LBBD DFJSP; TST RFJSP-SDST; RHO FJSP (arXiv:2502.15791, Graph-RHO 2026); RHC assembly (arXiv:2607.26482).

**Compositional theorem:** RHC→CP-SAT frozen algebra (W13) is insufficient if RHC→ALNS ignores op-id offsets after pred clear, or ERROR×virtualization forces silent greedy.

## CRITICAL

| ID | Finding |
|---|---|
| **C14-crash** | Early-greedy path: `per_window_limit` UnboundLocal |
| **C14-1** | ALNS repair/reanchor ignore kwargs offsets when pred cleared |
| **C14-2** | ALNS ERROR on frozen×parallel → RHC silent greedy branding |

## HIGH

| ID | Finding |
|---|---|
| **H14-1** | ALNS reanchor returns illegal schedule on stall |
| **H14-5** | Offset default `0.0` |
| **H14-nogood** | Empty LBBD nogood silent skip |
