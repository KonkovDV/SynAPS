# Literature brief Wave 13 (Aug 2026) — architecture & algebra

| Theme | Source | SynAPS implication |
|---|---|---|
| LBBD + critical-path cuts | CJME 2026; EJOR 329 (2026); Hooker LBBD | Keep KI-S3: only monotone/sound cuts; refuse invalid optimality cuts |
| FJSP-SDST + CP repair | IJIEC C-VNS-CP; TST 2026 RFJSP-SDST | Window/RHC repair must preserve SDST + resource algebra vs frozen |
| GPMS / rich temporal CP | ICAPS 2026 GPMS | Frozen intervals + setups + secondary resources are first-class |
| Monotone Benders | Hooker encyclopedia / emergent practice | Empty/skipped nogoods are fail-open — refuse |

**Compositional theorem (Wave 13):** Unit-correct CP-SAT frozen algebra is worthless if RHC clears predecessor edges and drops `frozen_context_*` before calling the inner solver.
