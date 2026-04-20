from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_native_rhc_candidate_acceleration_study_writes_report(tmp_path: Path) -> None:
    output_path = tmp_path / "native-rhc-candidate-report.json"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmark.study_native_rhc_candidate_acceleration",
            "--sizes",
            "64",
            "--repeats",
            "1",
            "--output",
            str(output_path),
        ],
        check=True,
    )

    assert output_path.exists()
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert "backend_status" in report
    assert "sizes" in report
    assert len(report["sizes"]) == 1

    size_payload = report["sizes"][0]
    assert size_payload["size"] == 64
    assert "results" in size_payload
    assert "consistency" in size_payload
    assert "speedups" in size_payload

    result_modes = {entry["mode"] for entry in size_payload["results"]}
    assert result_modes == {"batch_python", "batch_active", "batch_active_np"}