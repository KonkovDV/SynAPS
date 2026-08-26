"""K2.4: cProfile ALNS-500 on unconstrained 5k@8 (same cell as И5.2)."""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
from io import StringIO
from pathlib import Path

from benchmark.evidence_common import REPO_ROOT, collect_environment, write_hashes
from benchmark.study_beam_alns_box import run_one

DEFAULT_OUT = REPO_ROOT / "benchmark" / "evidence" / "alns-profile-2026-08-27"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    profiler = cProfile.Profile()
    profiler.enable()
    record = run_one(
        n_operations=5000,
        n_machines=8,
        solver_config="ALNS-500",
        seed=args.seed,
        night_analog=False,
        boxed=True,
    )
    profiler.disable()
    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats("tottime")
    stats.print_stats(10)
    top_text = stream.getvalue()
    rows: list[dict[str, object]] = []
    for func, (cc, _nc, tt, _ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]
        filename, line, name = func
        rows.append(
            {
                "ncalls": cc,
                "tottime": round(tt, 6),
                "file": filename,
                "line": line,
                "func": name,
            }
        )
    rows.sort(key=lambda row: float(row["tottime"]), reverse=True)
    top10 = rows[:10]
    lead = top10[0] if top10 else None
    one_liner = (
        f"construction in {lead['func']} ({lead['file']}:{lead['line']}) "
        f"tottime={lead['tottime']}s ncalls={lead['ncalls']}"
        if lead
        else "construction unknown (empty profile)"
    )
    payload = {
        "protocol": "alns-500-5k8-cprofile-2026-08-27",
        "run": record,
        "one_liner": one_liner,
        "top10_tottime": top10,
        "pstats_head": top_text[-8000:],
    }
    (out_dir / "environment.json").write_text(
        json.dumps(collect_environment(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "profile.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "one_liner.txt").write_text(one_liner + "\n", encoding="utf-8")
    files = sorted(
        path for path in out_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    write_hashes(out_dir, files)
    print(one_liner, flush=True)
    print(top_text, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
