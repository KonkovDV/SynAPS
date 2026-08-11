# Wave 10 — permanent deferral decisions

Decisions locked 2026-08-11 (Wave 10). Do not reopen without a new RFC + Red Team.

| Item | Decision | Status |
|---|---|---|
| CP-SAT energy term | **Done** — scaled arc term; default weight 0 | closed |
| Native ABI for `p_{o,m}` | **Permanent deferral** — skip-to-Python when overrides present | deferred |
| dmorill FJSSP_SDST pack | **Permanent forbid** — GPL-3.0; never vendor | forbidden |
| KI-S3 BHK subset monotone | **Keep accepted sentinel** — no discountable cuts until a sound monotone LB exists | accepted |

Rationale: native ABI is a Rust megaproject; GPL vendoring is a license risk; KI-S3
cuts were already removed because `L(S)-L(S\{j})` over-claims. Energy search was
the last actionable hole and is closed in CP-SAT this wave.
