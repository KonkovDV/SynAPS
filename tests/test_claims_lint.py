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

_REQUIRED_KI = tuple(f"KI-N{i}" for i in range(1, 15))


def test_claims_denylist_in_front_matter() -> None:
    hits: list[str] = []
    for rel in _SCAN_FILES:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        lowered = text.lower()
        for phrase in _FORBIDDEN:
            if phrase in lowered:
                hits.append(f"{rel}: {phrase}")
    assert not hits, f"forbidden claim phrase(s): {hits}"


def test_known_issues_lists_n1_through_n14() -> None:
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


def test_verify_claims_fails_on_planted_forbidden_word(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("SynAPS is industrially deployed.\n", encoding="utf-8")
    for name in ("README_RU.md", "KNOWN_ISSUES.md", "CHANGELOG.md"):
        (tmp_path / name).write_text("# x\n", encoding="utf-8")
    (tmp_path / "benchmark").mkdir()
    (tmp_path / "benchmark" / "README.md").write_text("# b\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_does_not_skip_on_bare_ne(tmp_path: Path) -> None:
    """A Russian «не» no longer blanks the rest of the line (Ж2.1)."""
    (tmp_path / "README.md").write_text(
        "Это не шутка: SynAPS is industrially deployed.\n",
        encoding="utf-8",
    )
    for name in ("README_RU.md", "KNOWN_ISSUES.md", "CHANGELOG.md"):
        (tmp_path / name).write_text("# x\n", encoding="utf-8")
    (tmp_path / "benchmark").mkdir()
    (tmp_path / "benchmark" / "README.md").write_text("# b\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def _planted_scan_root(tmp_path: Path, *, readme_ru: str, changelog: str = "# x\n") -> None:
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "README_RU.md").write_text(readme_ru, encoding="utf-8")
    (tmp_path / "KNOWN_ISSUES.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (tmp_path / "benchmark").mkdir()
    (tmp_path / "benchmark" / "README.md").write_text("# b\n", encoding="utf-8")


def test_verify_claims_fails_on_unsourced_wall_time(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Cover finished in 145 s.\n", encoding="utf-8")
    for name in ("README_RU.md", "KNOWN_ISSUES.md", "CHANGELOG.md"):
        (tmp_path / name).write_text("# x\n", encoding="utf-8")
    (tmp_path / "benchmark").mkdir()
    (tmp_path / "benchmark" / "README.md").write_text("# b\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_russian_dokazano(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Покрытие доказано на 5k.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_russian_garantiya(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Это гарантия полноты покрытия.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_russian_optimaln(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Решатель выдаёт оптимальный план.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_russian_vnedren(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Система уже внедрена на заводе.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_russian_promyshlenno(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Промышленно готовый APS-контур.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_russian_unikaln(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Уникальный алгоритм покрытия.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_russian_best_in_world(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Лучший в мире планировщик смен.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_cyrillic_seconds_without_evidence(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Покрытие за 145с на этой машине.\n")  # noqa: RUF001
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_nospace_seconds_without_evidence(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Покрытие за 13.7s на этой машине.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1


def test_verify_claims_fails_on_cyrillic_gib_without_evidence(tmp_path: Path) -> None:
    _planted_scan_root(tmp_path, readme_ru="Пик RSS 3.96 ГБ на лестнице.\n")
    completed = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "verify_claims.py"), "--root", str(tmp_path)],
        check=False,
        cwd=_ROOT,
    )
    assert completed.returncode == 1
