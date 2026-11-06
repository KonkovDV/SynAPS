"""Platform wheels uploaded to PyPI stay project synaps and keep synaps_native."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "merge_synaps_native_wheel.py"


def _load():
    spec = importlib.util.spec_from_file_location("merge_synaps_native_wheel", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["merge_synaps_native_wheel"] = module
    spec.loader.exec_module(module)
    return module


def _wheel(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def test_merge_keeps_synaps_name_and_native_extension(tmp_path: Path) -> None:
    pure = tmp_path / "pure" / "synaps-0.1.0-py3-none-any.whl"
    native = tmp_path / "native" / "synaps_native-0.3.0-cp313-cp313-win_amd64.whl"
    pure.parent.mkdir()
    native.parent.mkdir()
    _wheel(
        pure,
        {
            "synaps/__init__.py": b"x = 1\n",
            "synaps-0.1.0.dist-info/METADATA": b"Name: synaps\nVersion: 0.1.0\n",
            "synaps-0.1.0.dist-info/WHEEL": (
                b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            ),
            "synaps-0.1.0.dist-info/RECORD": b"synaps/__init__.py,,\n",
        },
    )
    _wheel(
        native,
        {
            "synaps_native/synaps_native.pyd": b"native-bytes",
            "synaps_native-0.3.0.dist-info/METADATA": b"Name: synaps_native\nVersion: 0.3.0\n",
            "synaps_native-0.3.0.dist-info/WHEEL": (
                b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp313-cp313-win_amd64\n"
            ),
        },
    )
    out = tmp_path / "out"
    built = _load().merge_wheel(pure, native, out)
    assert built.name == "synaps-0.1.0-cp313-cp313-win_amd64.whl"
    with zipfile.ZipFile(built) as archive:
        names = set(archive.namelist())
        assert "synaps/__init__.py" in names
        assert "synaps_native/synaps_native.pyd" in names
        assert not any(name.startswith("synaps_native-0.3.0.dist-info/") for name in names)
        metadata = archive.read("synaps-0.1.0.dist-info/METADATA").decode()
        wheel = archive.read("synaps-0.1.0.dist-info/WHEEL").decode()
        record = archive.read("synaps-0.1.0.dist-info/RECORD").decode()
    assert "Name: synaps" in metadata
    assert "Version: 0.1.0" in metadata
    assert "Root-Is-Purelib: false" in wheel
    assert "Tag: cp313-cp313-win_amd64" in wheel
    assert "synaps_native/synaps_native.pyd,sha256=" in record
    digest = hashlib.sha256(b"native-bytes").digest()
    token = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert f"sha256={token}" in record


def test_pure_dir_requires_one_pure_wheel(tmp_path: Path) -> None:
    module = _load()
    with pytest.raises(SystemExit):
        module._pure_wheel(tmp_path)
