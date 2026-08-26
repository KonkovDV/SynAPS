"""Claims lint (KI-N11): denylist + required known-issue ids."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_SCAN_FILES = (
    "README.md",
    "README_RU.md",
    "CHANGELOG.md",
    "KNOWN_ISSUES.md",
)

_FORBIDDEN = (
    "industrially deployed",
    "world record",
)

_REQUIRED_KI = tuple(f"KI-N{i}" for i in range(1, 13))


def test_claims_denylist_in_front_matter() -> None:
    hits: list[str] = []
    for rel in _SCAN_FILES:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        lowered = text.lower()
        for phrase in _FORBIDDEN:
            if phrase in lowered:
                hits.append(f"{rel}: {phrase}")
    assert not hits, f"forbidden claim phrase(s): {hits}"


def test_known_issues_lists_n1_through_n12() -> None:
    text = (_ROOT / "KNOWN_ISSUES.md").read_text(encoding="utf-8")
    missing = [kid for kid in _REQUIRED_KI if kid not in text]
    assert not missing, f"KNOWN_ISSUES.md missing {missing}"


def test_changelog_unreleased_points_at_hashed_ladder() -> None:
    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text.split("## [")[1]
    assert "cover-ladder-2026-08-25" in unreleased
    assert "3.96" in unreleased


def test_verify_claims_script_exits_zero() -> None:
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(_ROOT)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 0
