#!/usr/bin/env python3
"""Fail CI when published docs use forbidden claim words (KI-N11 / C3)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FORBIDDEN = (
    r"\boptimally\b",
    r"\bguarantees\b",
    r"industrially deployed",
    r"\bвнедр[её]н(?:ный|ая|ое|ые|ных)?\b",
    r"\bгарантирует\b",
    r"\bоптимально\b",
)
# `proven` is allowed only next to the empty-notary tautology.
PROVEN_OK = re.compile(
    r"proven_hard_violations\s*=\s*[∅Ø]|empty-notary|empty notary|notary empty",
    re.I,
)

NEGATION = re.compile(
    r"\bnot\b.{0,40}|\bне\b.{0,40}|non-claims|не заявлено|"
    r"forbidden unless|words forbidden|not claimed",
    re.I,
)

_SKIP_EVIDENCE = ("50K", "SEARCH_COVER")


def _unreleased_changed(changelog: str) -> str:
    """Honesty-close surface: first ### Changed under [Unreleased], not the historical dump."""
    parts = re.split(r"\n## \[", changelog, maxsplit=2)
    unreleased = parts[1] if len(parts) > 1 else changelog
    chunks = re.split(r"\n### ", unreleased, maxsplit=2)
    for chunk in chunks:
        if chunk.startswith("Changed") or chunk.lstrip().startswith("Changed"):
            return chunk
        if "\nChanged" in chunk[:40]:
            return chunk
    # Fallback: first 80 lines of Unreleased.
    return "\n".join(unreleased.splitlines()[:80])


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root: Path = args.root
    hits: list[str] = []
    for path in _scan_paths(root):
        text = path.read_text(encoding="utf-8")
        body = _unreleased_changed(text) if path.name == "CHANGELOG.md" else text
        prev = ""
        for i, line in enumerate(body.splitlines(), start=1):
            skip = bool(NEGATION.search(line))
            if not skip and NEGATION.search(prev) and line.startswith(" "):
                skip = True
            prev = line
            if skip:
                continue
            if "proven" in line.lower() and PROVEN_OK.search(line):
                continue
            for pattern in FORBIDDEN:
                if re.search(pattern, line, re.I) and "proven_hard_violations" not in line:
                    hits.append(f"{path.relative_to(root)}:{i}: {pattern}")
            if (
                re.search(r"\bproven\b", line, re.I)
                and not PROVEN_OK.search(line)
                and "except" not in line.lower()
                and "tautolog" not in line.lower()
            ):
                hits.append(f"{path.relative_to(root)}:{i}: proven")
    if hits:
        print("verify_claims: forbidden phrasing\n" + "\n".join(hits[:50]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
