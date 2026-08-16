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


def test_known_issues_registry_exists_and_lists_ki_ids() -> None:
    text = _REGISTRY.read_text(encoding="utf-8")
    assert "KI-S3" in text
    assert "test_guard_s3_bhk_bound_subset_monotone" in text
