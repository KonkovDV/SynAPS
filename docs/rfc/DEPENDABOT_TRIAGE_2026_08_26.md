# Dependabot open-PR triage — 2026-08-26

Seven PRs were open on `KonkovDV/SynAPS` master. All were Dependabot.
Leaving them open contradicted the supply-chain hygiene the README claims.
None were merged as-is: they targeted an April/May tree, auto-rebase was
disabled after 30 days, and CI on those branches is stale (failed or cancelled).

| PR | Title | Decision | Reason |
| --- | --- | --- | --- |
| 1 | `upload-artifact` 7.0.0 → 7.0.1 | **close; applied on HEAD** | Patch pin applied on current master (`043fb46…` / v7.0.1). Merging the April branch would replay four-month-old CI. |
| 2 | `pytest-benchmark>=5.2.3` | **close** | Floor already satisfied: `requirements-dev-lock.txt` has `pytest-benchmark==5.2.3`. |
| 3 | `torchrl>=0.11.1` | **close** | Optional extra `[rl]`. No CI job installs it. Floor bump without a lockfile/job is not hygiene. |
| 4 | `sglang>=0.5.10.post1` | **close** | Optional extra `[llm]`. Same as PR 3. |
| 5 | `mypy>=1.20.0` | **close** | Floor already satisfied: lock has `mypy==2.1.0`. |
| 6 | `torch-geometric>=2.7.0` | **close** | Optional extra `[ml]`. Same as PR 3. |
| 7 | `dependency-review-action` 4.9.0 → 5.0.0 | **close; applied on HEAD** | Node 24 runtime, hosted `ubuntu-latest` is sufficient. Pin applied on current master (`a1d282b…` / v5.0.0). `deny-licenses` remains, marked deprecated upstream; not removed here. |

Written close comments go on the GitHub PRs. This file is the in-tree ledger.
