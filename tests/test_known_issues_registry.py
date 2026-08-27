"""T-41 / F15: every intentional xfail in redteam guards is registered."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_GUARDS = _ROOT / "tests" / "test_redteam_guards.py"
_REGISTRY = _ROOT / "KNOWN_ISSUES.md"

_XFAIL_DECORATOR = re.compile(r"xfail")


def _xfail_test_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            text = ast.dump(deco)
            if "xfail" in text:
                names.append(node.name)
                break
    return names


def test_every_redteam_xfail_has_known_issues_entry() -> None:
    registry = _REGISTRY.read_text(encoding="utf-8")
    missing = [name for name in _xfail_test_names(_GUARDS) if name not in registry]
    assert not missing, (
        "xfail sentinel(s) in test_redteam_guards.py lack a KNOWN_ISSUES.md "
        f"entry (T-41 / F15): {missing}"
    )


def test_evidence_failure_taxonomy_has_known_issue_rows() -> None:
    """C2: every Failure taxonomy category in current evidence MDs has a KI-* id."""
    root = Path(__file__).resolve().parent.parent
    registry = (root / "KNOWN_ISSUES.md").read_text(encoding="utf-8")
    slug = re.compile(r"\| `([a-z0-9-]+)` \|")
    missing: list[str] = []
    for name in (
        "BENCHMARK_EVIDENCE_COVER_2026_08_26.md",
        "BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md",
    ):
        text = (root / "benchmark" / name).read_text(encoding="utf-8")
        in_section = False
        for line in text.splitlines():
            if line.startswith("## Failure taxonomy"):
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            match = slug.match(line.strip())
            if in_section and match:
                token = match.group(1)
                if token not in registry:
                    missing.append(f"{name}:{token}")
    assert not missing, missing


def test_known_issues_registry_exists_and_lists_ki_ids() -> None:
    text = _REGISTRY.read_text(encoding="utf-8")
    assert "KI-S3" in text
    assert "test_guard_s3_bhk_bound_subset_monotone" in text
    assert "KI-N1" in text
    assert "KI-N7" in text
    assert "KI-N12" in text
    assert "KI-N13" in text
    assert "KI-N14" in text
    assert "KI-N15" in text
    assert "test_study_solver_scaling_compares_requested_solvers_for_large_preset" in text
