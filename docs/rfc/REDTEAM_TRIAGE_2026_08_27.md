# Red Team triage — kernel honesty 2026-08-27

Hostile pass on the SynAPS kernel (`synaps/`), evidence hash surface, and
published K2 measurements. Method: contract oracles (`FEASIBLE` /
`verified_feasible` / stamp / notary), evidence SHA-256 ratchets, leftover
classifier vs occupancy, security grep (pickle / `eval` / path traversal /
subprocess), plus the branch-diff security review on
`measure/k2-calendar-n3-alns`.

This is **triage**, not a line-by-line of every solver. ALNS / CP-SAT / LBBD
bodies were not re-audited instruction-by-instruction. Open KI-N* rows stay
authoritative unless a row below closes or reclassifies them.

Not bitwise identity. Not OPTIMAL. Not a Linux re-run of K2.1 or K2.4.
Hashed COVER / cable / deadzone JSON not rewritten.

## Verdict

**No P0 on the customer FEASIBLE oracle.** Empty success is already demoted
(`stamp_honest_coverage`). `verify_schedule_result.feasible` is True only for
`FEASIBLE` / `OPTIMAL` with empty `proven_hard_violations`. Incomplete
coverage may remain `FEASIBLE` on the solver object (ADR-0005) but the
independent notary emits `MISSING_ASSIGNMENT`, so `verified_feasible` stays
false and the portfolio API raises on success-status + failed notary.

**Ship the two P1 closes in this change** (notary skip; unhashed BEAM JSON).
Residuals below stay open. Do not start K3, SignFlow, or a COVER retune from
this document.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **RT27-P1-A** | P1 | `verify_schedule_result` returned empty kinds whenever status was not `FEASIBLE`/`OPTIMAL`. K2.1 then published `independent_violation_kinds=[]` next to solver notary `CALENDAR_VIOLATION`. `feasible` was already False (not a false-Yes). | Checker runs on ERROR / TIMEOUT / INFEASIBLE **when assignments are nonempty**. `feasible` stays False. Empty-assignment failures still skip (500k `MISSING_ASSIGNMENT` flood). KI-N15. Node: `tests/test_calendar.py::test_verify_error_with_assignments_still_runs_notary` |
| **RT27-P1-B** | P1 | Cited boxed BEAM-3 3000@4 night cell sat on disk outside `SHA256SUMS.txt`. KI-N2 pointed at a run past 120 s with no digest. | File hashed; MD table matches sums. Node: `tests/test_evidence_sha256sums.py::test_beam_alns_box_run_json_files_are_listed_in_sha256sums` |

Planted fails that had to go red before the fix:

| Test | Before |
|------|--------|
| `test_verify_error_with_assignments_still_runs_notary` | `CALENDAR_VIOLATION` not in `[]` |
| `test_beam_alns_box_run_json_files_are_listed_in_sha256sums` | `run_3000ops_4m_BEAM_3_night_boxed_seed1.json` missing from sums |

## P0 (none this pass)

| Attack | Result |
|--------|--------|
| `FEASIBLE` / `verified_feasible=true` with nonempty `proven_hard_violations` | **blocked** — customer oracle is `not proven` |
| Empty assignments + success status | **blocked** — stamp demotes to `ERROR` (`tests/test_coverage_outcome.py`) |
| ERROR with clean assignments becoming `verified_feasible` | **blocked** — `feasible` requires success status (`test_verify_error_with_clean_assignments_is_not_verified_feasible`) |
| Unchecked self-report as Yes | **blocked** on the default portfolio path; `--no-verify-feasibility` and `run_benchmark.py` `verify_feasibility=False` still run an independent `verify_schedule_result` afterwards (harness) or skip (CLI flag) — CLI skip is residual P2 |

## Live residuals

| ID | Sev | Finding | Next honest step |
|----|-----|---------|------------------|
| **RT27-R1** | P1 | Leftover classifier labels **unplaced** ops only. K2.1 notary `CALENDAR_VIOLATION` count exceeds leftover (seed 1: 289 vs 239). Some **placed** occupancy faults. Classifier is not a notary. Published calendar JSON not rewritten. | Keep the two tallies separate. Do not treat `NO_CREW_CAPACITY` as occupancy-clean. Optional: `synaps recheck` on stored assignments (K3). |
| **RT27-R2** | P1 | Hash-gate `_CURRENT` / `_STUDY` still allowlists three COVER / cable / deadzone MD files. Calendar 3000, ALNS profile, N3 session MDs stay outside by construction (K3.2). This pass only ratchets the cited BEAM/ALNS folder. | Glob `BENCHMARK_EVIDENCE_*.md` + sibling `SHA256SUMS.txt` in K3. |
| **RT27-R3** | P1 | `BeamSearchDispatch._solve_core` still does not read `time_limit_s`. Hashed proof: BEAM-3 3000@4 boxed seed 1, `wall_time_s=12632.756`, `time_limit_s_kwarg=120`, `status=timeout`, ratio 0.224, `verified_feasible=false` (`benchmark/evidence/beam-alns-box-2026-08-26/run_3000ops_4m_BEAM_3_night_boxed_seed1.json`). KI-N2. Time-box enforcement is K3, not this close. | xfail / enforce in K3. Do not unbox the 12-cell matrix to "prove" the box. |
| **RT27-R4** | P1 | Native COVER skips when any work-center calendar is set (Python clip). Forced `RHC-GREEDY-COVER` on a calendar instance is not a native occupancy proof. Router still keeps calendar instances inside `CALENDAR_AWARE`. | Keep skip; do not claim native COVER for signs. |
| **RT27-R5** | P2 | K2.1 published `independent_violation_kinds=[]` under the old skip. Those JSON bytes stay. Re-runs after KI-N15 will populate kinds; that is not a rewrite of the hashed calendar folder. | Cite solver notary on that study, or re-run a new session. |
| **RT27-R6** | P2 | Deadzone session `SHA256SUMS.txt` (Windows recapture, Linux N3) is not in the COVER/deadzone root CI sums tests. Root freeze still is. | Session-dir ratchet, or fold into K3.2 glob. |
| **RT27-R7** | P2 | `synaps solve --no-verify-feasibility` can emit solver `FEASIBLE` without the customer oracle. Default path verifies. | Keep the flag; do not document it as a Yes. |
| **RT27-R8** | P3 | K3 remainder: README_RU sourced >=90%, glob hash gate, time-box xfail BEAM, `assignments` + `synaps recheck`, architectural stamp test. Deadline 14.09.2026. Do not start until asked. | Ordered K3. |
| **KI-N3** | — | Reclassified `algorithmic` on this branch (PR #14). Not on `master` until merge. Sentinel `test_hashed_8k4_remainder_stays_worker_error` still requires hashed epoch `worker_error`. | Merge #14; do not rewrite epoch JSON. |
| **KI-N12 / KI-N14** | — | Domain pin lag; `test-slow` red on LBBD-10 `results.feasible`. Unchanged. | K5 pin rewrite of one side; narrow (c) on the stale assert. |

## Security grep (not a pentest)

| Surface | Result |
|---------|--------|
| `pickle` / `eval` / `exec` in `synaps/` | **none** |
| `problem_instance_ref` | Fail-closed: relative, stays inside `instance_dir`, `.json` only, size cap (`synaps/contracts.py`) |
| `subprocess` | Tests and benchmark isolates, not the kernel import path |
| Native list-schedule | Calendar and duration-override skip to Python (fail-closed, not a silent Yes) |

No credentials, no GridPlan/MobiRoute/AeroBIM trees, no `C:\plans`.

## Forbidden claims

Do not add: bitwise ALNS/RHC, OPTIMAL, SOTA, INFIMUM, C5a, N-1, SAIDI, live
EL5, MAST, industrial deployment, ЦОДД / Мосгортранс / Россети as customers,
0.7702 as machine-calendar or sign coverage, a Yes on 5k@8, Linux green for
K2.1 / K2.4 (those are Windows; write «не проверено на Linux»), a COVER
50k–500k retraction from KI-N14, a retune of `global_greedy_cover_min_ops`.

## Numbers used here (sourced)

| Claim | Source |
|-------|--------|
| BEAM-3 3000@4 boxed seed 1 wall 12632.756 s, ratio 0.224, timeout | `benchmark/evidence/beam-alns-box-2026-08-26/run_3000ops_4m_BEAM_3_night_boxed_seed1.json` |
| Calendar 3000@8 leftover vs notary (289 vs 239 seed 1) | `benchmark/BENCHMARK_EVIDENCE_CALENDAR_3000_8M_2026_08_27.md` |
| KI-N3 Linux ratios | run [33021109132](https://github.com/KonkovDV/SynAPS/actions/runs/33021109132), session `n3-linux-2026-08-27` |

## Next honest step

Merge PR #14 after required Linux jobs. Do not create `synaps-signflow`.
Do not glob-rewrite hashed JSON. K3 only when asked.
