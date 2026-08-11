# Literature + algebra brief (Aug 2026) — SynAPS Wave 12

Sources consulted (2025–2026):

| Theme | Anchor | Implication for SynAPS |
|---|---|---|
| FJSP-SDST + CP-assisted VNS | IJIEC C-VNS-CP (2024/25) | CP repair must respect full SDST, not only no-overlap |
| Enhanced LBBD for FJSP flex | CJME 2026 (Cheng et al.) | Keep cut-free sound master; refuse invalid optimality cuts (KI-S3) |
| LBBD for DFJSP | EJOR 329 (2026) | Strong subproblem relaxations — SynAPS reports LB without unsound cuts |
| RFJSP-SDST + IL+CP EA | TST 2026 | Resource-constrained setups: frozen aux must reserve pools |
| Energy + CP-SAT globals | IJAMT 2026 moulding; arXiv:2601.06542 TOU-LBBD | Energy stays optional weight-0; native globals preferred over hand encodings |
| Algorithm selection / frugal ASP | JAIR 2026; Computers&OR 2026 | Advisory must emit **registry-valid** solver names |

Algebra stance for Wave 12: frozen CP-SAT intervals without SDST/aux adjacency are **unsound** relative to FeasibilityChecker (setup window `[start−setup, end)`).
