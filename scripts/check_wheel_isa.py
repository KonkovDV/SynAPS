#!/usr/bin/env python3
"""Release gate (T-03a / R-10): an x86-64 native wheel must run without AVX.

The repo's ``.cargo/config.toml`` builds with ``target-cpu=native`` for local
speed. A wheel built that way carries the build host's ISA (AVX2 / AVX-512)
and kills the interpreter with SIGILL on an older CPU before the Python
fallback in ``synaps/accelerators.py`` can engage. ``release.yml`` therefore
pins ``RUSTFLAGS=-C target-cpu=x86-64-v2``; this script proves the result.

1. **Static.** Disassemble every ELF shared object in the wheel and count
   AVX-family instructions: any VEX / EVEX encoding (mnemonics ``v*`` —
   including 128-bit ``vmovdqu %xmm0``, which a CPU without AVX rejects just
   like a ``ymm`` form), and separately ``%ymm`` / ``%zmm`` operands.
   ``x86-64-v2`` (SSE4.2 / POPCNT) has none of them.
2. **Dynamic** (``--qemu-python``). Import the module and run a scalar and a
   batch kernel under qemu user-mode emulation of a CPU without AVX
   (``Nehalem`` by default). A ``native`` build dies there with SIGILL.

Usage::

    python scripts/check_wheel_isa.py dist-native/*.whl
    python scripts/check_wheel_isa.py dist-native/*.whl --qemu-python venv/bin/python

Exit status 0 = portable; 1 = AVX found, an x86-64 wheel has no ELF, or the emulated import failed.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

#: VMX / segment-verify mnemonics that start with "v" but are not VEX-encoded.
_NOT_VEX = frozenset(
    {
        "verr",
        "verw",
        "vmcall",
        "vmclear",
        "vmfunc",
        "vmlaunch",
        "vmptrld",
        "vmptrst",
        "vmread",
        "vmresume",
        "vmwrite",
        "vmxoff",
        "vmxon",
    }
)
_INSTRUCTION = re.compile(r"^\s*[0-9a-f]+:\s+(?P<mnemonic>[a-z][a-z0-9.]*)\b(?P<operands>.*)$")

SMOKE = """
import synaps_native as n
score = n.compute_atcs_log_score(2.0, 5.0, 3.0, 4.0, 1.0, 2.0, 1.0, 1.0, 0.0, 1.0, 1.0)
assert score == score, "NaN from the scalar kernel"
size = 4096
batch = n.compute_atcs_log_scores_batch(
    [1.0 + i % 7 for i in range(size)], [1.0 + i % 11 for i in range(size)],
    [float(i % 13) for i in range(size)], 4.0, [float(i % 3) for i in range(size)],
    [2.0] * size, 1.0, 1.0, [0.0] * size, 1.0, 1.0,
)
assert len(batch) == size
print("synaps_native ok under emulation:", round(score, 6), round(sum(batch), 3))
"""


def avx_counts(shared_object: Path, objdump: str = "objdump") -> dict[str, int]:
    """Counts of VEX/EVEX instructions and of ymm / zmm operands in a binary."""
    listing = subprocess.run(
        [objdump, "-d", "--no-show-raw-insn", str(shared_object)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return count_avx(listing)


def count_avx(listing: str) -> dict[str, int]:
    """Counts over an AT&T ``objdump -d --no-show-raw-insn`` listing."""
    counts = {"vex_or_evex": 0, "ymm": 0, "zmm": 0, "instructions": 0}
    for line in listing.splitlines():
        match = _INSTRUCTION.match(line)
        if match is None:
            continue
        counts["instructions"] += 1
        mnemonic = match["mnemonic"]
        if mnemonic.startswith("v") and mnemonic not in _NOT_VEX:
            counts["vex_or_evex"] += 1
        operands = match["operands"]
        counts["ymm"] += "%ymm" in operands
        counts["zmm"] += "%zmm" in operands
    return counts


def _is_x86_64_elf(path: Path) -> bool:
    header = path.read_bytes()[:20]
    # ELF magic, then e_machine (bytes 18-19, little endian) 0x3E = x86-64.
    return header[:4] == b"\x7fELF" and header[18:20] == b"\x3e\x00"


def _expects_x86_64_elf(wheel: Path) -> bool:
    """True when the wheel tag says this archive should contain an x86-64 ``.so``."""
    name = wheel.name
    return "x86_64" in name and ("manylinux" in name or "linux" in name)


def check_wheel(wheel: Path) -> bool:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(tmp)
        objects = [p for p in Path(tmp).rglob("*.so") if _is_x86_64_elf(p)]
        if not objects:
            if _expects_x86_64_elf(wheel):
                print(f"{wheel.name}: x86-64 wheel has no ELF shared object")
                return False
            print(f"{wheel.name}: no x86-64 ELF shared object (nothing to check)")
            return True
        for shared_object in objects:
            counts = avx_counts(shared_object)
            dirty = counts["vex_or_evex"] or counts["ymm"] or counts["zmm"]
            verdict = "FAIL: AVX-family code" if dirty else "ok: no AVX-family code"
            print(f"{wheel.name}::{shared_object.name}: {counts} -> {verdict}")
            ok = ok and not dirty
    return ok


def check_emulated_import(python: Path, cpu: str) -> bool:
    qemu = shutil.which("qemu-x86_64")
    if qemu is None:
        print("qemu-x86_64 not found (apt-get install qemu-user)")
        return False
    run = subprocess.run(
        [qemu, "-cpu", cpu, str(python), "-c", SMOKE], capture_output=True, text=True
    )
    print(run.stdout.strip() or run.stderr.strip()[-2000:])
    if run.returncode != 0:
        signal = -run.returncode if run.returncode < 0 else run.returncode - 128
        print(f"emulated import on {cpu} failed: exit {run.returncode} (signal {signal}?)")
    return run.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheels", nargs="+", type=Path)
    parser.add_argument(
        "--qemu-python",
        type=Path,
        help="interpreter with the wheel installed; run the smoke under qemu-x86_64",
    )
    parser.add_argument("--qemu-cpu", default="Nehalem", help="qemu CPU model without AVX")
    args = parser.parse_args(argv)
    verdicts = [check_wheel(wheel) for wheel in args.wheels]  # report every wheel
    ok = all(verdicts)
    if args.qemu_python is not None:
        ok = check_emulated_import(args.qemu_python, args.qemu_cpu) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
