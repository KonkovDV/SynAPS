"""T-03a: the release ISA gate counts every AVX-family encoding, not only ymm / zmm."""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_wheel_isa.py"

_LISTING = """
synaps_native.so:     file format elf64-x86-64

0000000000001000 <kernel>:
    1000:\tmovaps %xmm1,%xmm0
    1004:\tpxor   %xmm2,%xmm2
    1008:\tvmovdqu %xmm0,(%rdi)
    100c:\tvaddpd %ymm1,%ymm2,%ymm3
    1010:\tvfmadd231pd %zmm1,%zmm2,%zmm3
    1016:\tvzeroupper
    1019:\tverw   %ax
    101c:\tret
"""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_wheel_isa", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_wheel_isa"] = module
    spec.loader.exec_module(module)
    return module


def test_vex_128_counts_as_avx_and_verw_does_not() -> None:
    counts = _load().count_avx(_LISTING)
    # vmovdqu xmm (VEX-128) + vaddpd ymm + vfmadd zmm + vzeroupper; not verw.
    assert counts == {"vex_or_evex": 4, "ymm": 1, "zmm": 1, "instructions": 8}


def test_x86_64_wheel_without_an_elf_fails(tmp_path: Path) -> None:
    wheel = tmp_path / "synaps_native-0.3.0-cp313-cp313-manylinux_2_28_x86_64.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("synaps_native-0.3.0.dist-info/WHEEL", "Tag: cp313\n")
    assert _load().check_wheel(wheel) is False


def test_windows_wheel_without_an_elf_is_out_of_scope(tmp_path: Path) -> None:
    wheel = tmp_path / "synaps_native-0.3.0-cp313-cp313-win_amd64.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("synaps_native-0.3.0.dist-info/WHEEL", "Tag: cp313\n")
    assert _load().check_wheel(wheel) is True


def test_sse_only_listing_is_clean() -> None:
    sse = "\n".join(line for line in _LISTING.splitlines() if "\tv" not in line or "\tverw" in line)
    counts = _load().count_avx(sse)
    assert counts["vex_or_evex"] == counts["ymm"] == counts["zmm"] == 0
    assert counts["instructions"] == 4  # movaps, pxor, verw, ret
