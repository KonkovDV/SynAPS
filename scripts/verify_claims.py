#!/usr/bin/env python3
"""Fail CI when published docs use forbidden claim words or unsourced timings.

KI-N11 / Ж2: skip is an explicit marker on the line or a tagged non-claims
block, not a ``не`` / ``not`` proximity heuristic.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FORBIDDEN = (
    r"\boptimally\b",
    r"\bguarantees\b",
    r"industrially deployed",
    r"\bвнедр[её]н\w*",
    r"\bгарант(?:ия|ированн\w*)",
    r"\bоптимальн\w*",
    r"\bдоказан(?:о|а|ы)\b",
    r"\bпромышленно\b",
    r"\bуникальн\w*",
    r"лучш\w*\s+в\s+мире",
)
PROVEN_OK = re.compile(
    r"proven_hard_violations\s*=\s*[∅Ø]|empty-notary|empty notary|notary empty",
    re.I,
)
CLAIMS_OK = re.compile(r"<!--\s*claims-ok\s*-->|#\s*claims-ok\s*$", re.I)
EXPLICIT_NONCLAIM = re.compile(
    r"Not claimed:|не заявлено:|\bnon-claims\b",
    re.I,
)
NON_CLAIMS_START = "<!-- non-claims:start -->"
NON_CLAIMS_END = "<!-- non-claims:end -->"
# Measured wall/memory, not config names like time_limit_s=120.
PERF_NUM = re.compile(
    r"(?<![\w./=_@-])~?\d+(?:[ \u00a0]\d{3})*(?:\.\d+)?\s*"
    r"(?:ms|сек|мин|GiB|MiB|ГБ|МБ|GB|MB|ч|s|с)\b"
)
CONFIGISH = re.compile(
    r"time_limit_s|timeout_s|watchdog|preferred_max_latency|CPSAT-\d+|latency budget",
    re.I,
)
EVIDENCE_REF = re.compile(
    r"benchmark/|BENCHMARK_EVIDENCE|KI-N\d+|docs/rfc/|cover-ladder|"
    r"deadzone|cable-c6|SHA256|evidence/",
    re.I,
)
_SKIP_EVIDENCE = ("50K", "SEARCH_COVER")


def _unreleased(changelog: str) -> str:
    """Entire [Unreleased] section, not only the first ### Changed."""
    parts = re.split(r"\n## \[", changelog, maxsplit=2)
    if len(parts) < 2:
        return changelog
    return parts[1]


def _scan_paths(root: Path) -> list[Path]:
    paths = [
        root / "README.md",
        root / "README_RU.md",
        root / "KNOWN_ISSUES.md",
        root / "CHANGELOG.md",
        root / "benchmark" / "README.md",
    ]
    for folder in ("docs/adr", "docs/preprint", "docs/architecture"):
        directory = root / folder
        if directory.is_dir():
            paths.extend(sorted(directory.glob("*.md")))
    bench = root / "benchmark"
    if bench.is_dir():
        for md in sorted(bench.glob("BENCHMARK_EVIDENCE_*.md")):
            if any(token in md.name for token in _SKIP_EVIDENCE):
                continue
            paths.append(md)
    return [path for path in paths if path.is_file()]


def _iter_active_lines(text: str) -> list[tuple[int, str, bool]]:
    """Yield (lineno, line, skipped) after applying block and line markers."""
    in_block = False
    out: list[tuple[int, str, bool]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped == NON_CLAIMS_START:
            in_block = True
            out.append((i, line, True))
            continue
        if stripped == NON_CLAIMS_END:
            in_block = False
            out.append((i, line, True))
            continue
        skipped = in_block or bool(CLAIMS_OK.search(line)) or bool(EXPLICIT_NONCLAIM.search(line))
        out.append((i, line, skipped))
    return out


def _number_needs_evidence(line: str) -> bool:
    return bool(PERF_NUM.search(line)) and not CONFIGISH.search(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args(argv)
    root: Path = args.root
    hits: list[str] = []
    stats: dict[str, tuple[int, int]] = {}
    for path in _scan_paths(root):
        text = path.read_text(encoding="utf-8")
        body = _unreleased(text) if path.name == "CHANGELOG.md" else text
        rows = _iter_active_lines(body)
        skipped_n = sum(1 for _i, _line, skipped in rows if skipped)
        stats[str(path.relative_to(root))] = (skipped_n, len(rows))
        for idx, (lineno, line, skipped) in enumerate(rows):
            if skipped:
                continue
            if "proven" in line.lower() and PROVEN_OK.search(line):
                continue
            for pattern in FORBIDDEN:
                if re.search(pattern, line, re.I) and "proven_hard_violations" not in line:
                    hits.append(f"{path.relative_to(root)}:{lineno}: {pattern}")
            if (
                re.search(r"\bproven\b", line, re.I)
                and not PROVEN_OK.search(line)
                and "except" not in line.lower()
                and "tautolog" not in line.lower()
            ):
                hits.append(f"{path.relative_to(root)}:{lineno}: proven")
            if _number_needs_evidence(line) and (
                path.name
                in {
                    "README.md",
                    "README_RU.md",
                    "CHANGELOG.md",
                    "KNOWN_ISSUES.md",
                }
                or path == root / "benchmark" / "README.md"
            ):
                prev = rows[idx - 1][1] if idx > 0 else ""
                nxt = rows[idx + 1][1] if idx + 1 < len(rows) else ""
                window = f"{prev}\n{line}\n{nxt}"
                if not EVIDENCE_REF.search(window):
                    hits.append(
                        f"{path.relative_to(root)}:{lineno}: "
                        "performance number without evidence file"
                    )
    if args.stats:
        for name, (skipped_n, total) in sorted(stats.items()):
            print(f"{name}: skipped {skipped_n}/{total}")
    if hits:
        print("verify_claims: forbidden phrasing\n" + "\n".join(hits[:80]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
