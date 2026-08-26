"""Fail CI when the public portfolio count drifts across registry and READMEs."""

from __future__ import annotations

import re
from pathlib import Path

from synaps.solvers.registry import available_solver_configs

_ROOT = Path(__file__).resolve().parents[1]
_README_EN = _ROOT / "README.md"
_README_RU = _ROOT / "README_RU.md"
_REPO_DESCRIPTION = _ROOT / ".github" / "repo_description.txt"

_EN_COUNT = re.compile(r"^(\d+) named configs in ", re.MULTILINE)
_RU_COUNT = re.compile(r"^(\d+) конфигурац", re.MULTILINE)
_DESC_COUNT = re.compile(r"(\d+) named solver configs")


def test_available_solver_configs_count_matches_readme_en_and_ru() -> None:
    registry_n = len(available_solver_configs())
    en = _README_EN.read_text(encoding="utf-8")
    ru = _README_RU.read_text(encoding="utf-8")
    en_match = _EN_COUNT.search(en)
    ru_match = _RU_COUNT.search(ru)
    assert en_match is not None, "README.md must state '<N> named configs in'"
    assert ru_match is not None, "README_RU.md must state '<N> конфигураци…'"
    en_n = int(en_match.group(1))
    ru_n = int(ru_match.group(1))
    assert en_n == registry_n, (
        f"README.md portfolio count {en_n} != registry {registry_n} ({available_solver_configs()})"
    )
    assert ru_n == registry_n, f"README_RU.md portfolio count {ru_n} != registry {registry_n}"


def test_github_repo_description_file_matches_registry_count() -> None:
    """Canonical GitHub About text. Live GitHub must be copied from this file."""
    registry_n = len(available_solver_configs())
    text = _REPO_DESCRIPTION.read_text(encoding="utf-8").strip()
    match = _DESC_COUNT.search(text)
    assert match is not None, "repo_description.txt must contain '<N> named solver configs'"
    assert int(match.group(1)) == registry_n
    assert "22 solver configs" not in text
