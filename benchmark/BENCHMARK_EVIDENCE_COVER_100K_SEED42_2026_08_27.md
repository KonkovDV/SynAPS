# COVER 100k@200 seed 42 recapture — 2026-08-27

> **Status:** Artifact-bound session. Not a rewrite of hashed
> `cover-ladder-2026-08-25/`. Not a native-wheel Yes.
> **Claim level:** one-seed recapture after residual append-scan.

Hashed ladder `run_100k_at_200_seed42.json` stays `stalled=true`
(KI-N4 epoch). This folder is a **new** run on the same generator kwargs.

## Protocol

```bash
python -m benchmark.study_cover_ladder --scales 100k@200 --seeds 42 --session-id n4-seed42-2026-08-27
```

Then moved to this top-level folder so the Artifact SHA-256 table has its
own `SHA256SUMS.txt`. Solver: `RHC-GREEDY-COVER`. Machine: Windows 11,
CPython 3.13, `native_backend=python` (`native_available=false`).
Do not mix this 40.137 s Python wall with hashed native siblings (~13 s).

## Result

| scale | seed | ops | ratio | verified | notary | makespan | wall s | RSS MB | native |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 100k@200 | 42 | 100000 | 1.0 | true | 0 | 33525.03 | 40.137 | 841.2 | python |

`status=feasible`. Independent `verified_feasible=true`.
`proven_hard_violations` empty. 131 leftovers after list-schedule were
placed by residual greedy with append scan (fell before fix: full gap walk
on the packed timeline hung >480 s).

## Non-claims

1. Not a rewrite of hashed COVER JSON. Hashed 100k@200 remains two of three.
2. Not native list-schedule (this process had no `synaps_native` wheel).
3. Not a retune of `global_greedy_cover_min_ops` or residual placement policy.
4. Not Linux. Linux COVER in PR CI is the 60k@100 seed 1 cell, not this file.
5. Not a three-seed hashed Yes at 100k.

## Artifact SHA-256

Directory `benchmark/evidence/cover-100k-seed42-2026-08-27/`. Rows from
`SHA256SUMS.txt` (working-tree bytes). `benchmark/evidence/**` is `-text`;
git-blob LF digest is the citable one after commit.

| File | SHA-256 |
|------|---------|
| `environment.json` | `9d9702e2332d47533570793886a2fc0fd8fd592dac4e8720e07df9cfea39d930` |
| `run_100k_at_200_seed42.json` | `e9073ea28640c43094538374ce3090b471f85adbce4237941e5cd4d40bf386d4` |
| `summary.json` | `a045a9cbcfca6ad4470d2dc8c4c01f499d00abc095b5e6be321d33f441fb6961` |
| `SHA256SUMS.txt` | `b55f4541db5b29f6c0556221333f8ae742c9660bdcb23a09b78f297922245328` |
