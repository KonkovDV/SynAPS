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
T_CRIT_95_N3 = 4.302652729911275  # Student t, df=2, two-tailed 0.05


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
    if n == 3 and sample_sd > 0:
        half_width = T_CRIT_95_N3 * sample_sd / (n**0.5)
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
            "Student t, df=n-1, two-tailed 0.05. n=3 ⇒ interval is wide; "
            "treat as a dispersion bound, not a quality claim."
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
