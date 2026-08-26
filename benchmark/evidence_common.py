"""Shared environment capture, SHA-256, and small-n stats for evidence studies."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median, pstdev, stdev
from typing import Any

from synaps.accelerators import get_acceleration_status

REPO_ROOT = Path(__file__).resolve().parents[1]
# Student t 0.975 quantile, index = df = n-1, for n in 2..31.
_T_CRIT_975 = (
    0.0,
    12.706204736432095,
    4.302652729911275,
    3.182446305284263,
    2.7764451051977987,
    2.5705818366147395,
    2.4469118511440436,
    2.364624251592784,
    2.306004135204166,
    2.2621571627409915,
    2.228138850958557,
    2.200985160082949,
    2.178812829667228,
    2.1603686564619728,
    2.1447866879169277,
    2.131449545559323,
    2.1199052992210112,
    2.1098155778331806,
    2.10092204024096,
    2.093024054408263,
    2.0859634472658364,
    2.079613844727662,
    2.0738730679040147,
    2.0686576104190406,
    2.0638985616280205,
    2.0595385527532946,
    2.055529438642871,
    2.0518305164802833,
    2.048407141795244,
    2.045229642132703,
    2.0422724563012373,
)
T_CRIT_95_N3 = _T_CRIT_975[2]


def t_crit_95(n: int) -> float | None:
    """Two-tailed 95% Student-t critical value for sample size n, or None."""

    df = n - 1
    if 1 <= df < len(_T_CRIT_975):
        return _T_CRIT_975[df]
    return None


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def cpu_flags() -> str | None:
    """Linux ``/proc/cpuinfo`` flags (AVX2/FMA3). None on Windows (KI-N10)."""

    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.is_file():
        return None
    try:
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            lowered = line.lower()
            if lowered.startswith("flags") or line.startswith("Features"):
                return line.split(":", 1)[-1].strip()
    except OSError:
        return None
    return None


def peak_rss_bytes() -> int | None:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return int(usage)
        return int(usage) * 1024
    except (ImportError, AttributeError, OSError):
        pass
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_info = psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        ok = get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        if ok:
            return int(counters.PeakWorkingSetSize)
    except (AttributeError, OSError, ValueError):
        pass
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Process -Id {os.getpid()}).PeakWorkingSet64",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return int(out.strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def collect_environment() -> dict[str, Any]:
    accel = get_acceleration_status()
    native_mod = None
    native_file = None
    try:
        import synaps_native

        native_mod = getattr(synaps_native, "__version__", None) or "present"
        native_file = getattr(synaps_native, "__file__", None)
    except ImportError:
        native_mod = None
    return {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "git_head": git_head(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "cpu_flags": cpu_flags(),
        "synaps_native": native_mod,
        "synaps_native_file": native_file,
        "acceleration": accel,
        "wheel_present": bool(accel.get("native_module_imported")),
        "list_schedule_cover_backend": accel.get("list_schedule_cover_backend"),
    }


def summarize_seed(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    n = len(ordered)
    avg = mean(ordered)
    sample_sd = stdev(ordered) if n > 1 else 0.0
    cv = (sample_sd / avg) if avg else None
    half_width = None
    t_crit = t_crit_95(n)
    if t_crit is not None and n >= 2 and sample_sd > 0:
        half_width = t_crit * sample_sd / (n**0.5)
    df = n - 1
    return {
        "n": n,
        "min": ordered[0],
        "median": median(ordered),
        "max": ordered[-1],
        "mean": avg,
        "stdev_sample": sample_sd,
        "stdev_population": pstdev(ordered) if n > 1 else 0.0,
        "cv": cv,
        "ci95_t_halfwidth": half_width,
        "ci95_t_low": (avg - half_width) if half_width is not None else avg,
        "ci95_t_high": (avg + half_width) if half_width is not None else avg,
        "ci95_note": (
            f"Student t, df={df}, two-tailed 0.05. "
            "n<2 or n>31 ⇒ no interval. Treat as a dispersion bound, not a quality claim."
        ),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_hashes(out_dir: Path, files: list[Path]) -> Path:
    lines = [f"{sha256_file(path)}  {path.relative_to(out_dir).as_posix()}" for path in files]
    target = out_dir / "SHA256SUMS.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
