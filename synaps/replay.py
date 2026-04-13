"""Replay artifact surfaces for SynAPS experiment and advisory pipelines."""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, Field

from synaps.contracts import CONTRACT_VERSION
from synaps.model import ScheduleProblem, ScheduleResult, SolverStatus
from synaps.problem_profile import build_problem_profile

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

REPLAY_ARTIFACT_VERSION: Final = "2026-04-05"


class ReplayObjectiveSnapshot(BaseModel):
    """Canonical objective vector recorded for one replayable run."""

    makespan_minutes: float = 0.0
    total_setup_minutes: float = 0.0
    total_tardiness_minutes: float = 0.0
    total_material_loss: float = 0.0
    weighted_sum: float = 0.0


class ReplayVerificationSnapshot(BaseModel):
    """Canonical feasibility snapshot recorded for one run."""

    performed: bool = True
    feasible: bool
    violation_count: int
    violation_kinds: list[str] = Field(default_factory=list)


class ReplayRoutingSnapshot(BaseModel):
    """Routing and orchestration hints that explain solver selection."""

    execution_mode: str = "solve"
    routed: bool = False
    routing_reason: str
    regime: str = "nominal"
    preferred_max_latency_s: int | None = None
    exact_required: bool | None = None


class ReplayBenchmarkArtifact(BaseModel):
    """Replay payload emitted by the benchmark harness for one solver run."""

    replay_artifact_version: Literal["2026-04-05"] = REPLAY_ARTIFACT_VERSION
    artifact_kind: Literal["benchmark-run"] = "benchmark-run"
    artifact_source: Literal["benchmark.run_benchmark"] = "benchmark.run_benchmark"
    contract_version: str = CONTRACT_VERSION
    instance_name: str
    instance_path: str
    solver_config: str
    selected_solver_config: str
    solver_name: str
    result_status: str
    feasible: bool
    proved_optimal: bool
    assignments: int
    objective: ReplayObjectiveSnapshot
    verification: ReplayVerificationSnapshot
    statistics: dict[str, int | float | bool | None] = Field(default_factory=dict)
    problem_profile: dict[str, int | float | bool | str] = Field(default_factory=dict)
    routing: ReplayRoutingSnapshot
    portfolio_metadata: dict[str, Any] = Field(default_factory=dict)


class ReplayRuntimeArtifact(BaseModel):
    """Replay payload emitted by solve and repair runtime surfaces."""

    replay_artifact_version: Literal["2026-04-05"] = REPLAY_ARTIFACT_VERSION
    artifact_kind: Literal["runtime-solve", "runtime-repair"]
    artifact_source: str
    contract_version: str = CONTRACT_VERSION
    request_id: str | None = None
    solver_config: str | None = None
    selected_solver_config: str
    solver_name: str
    result_status: str
    feasible: bool
    proved_optimal: bool
    assignments: int
    objective: ReplayObjectiveSnapshot
    verification: ReplayVerificationSnapshot
    problem_profile: dict[str, int | float | bool | str] = Field(default_factory=dict)
    routing: ReplayRoutingSnapshot
    request_summary: dict[str, Any] = Field(default_factory=dict)
    portfolio_metadata: dict[str, Any] = Field(default_factory=dict)


def _coerce_int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _coerce_bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _result_is_feasible(result: ScheduleResult) -> bool:
    return result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}


def _build_verification_snapshot(
    portfolio_metadata: dict[str, Any], result: ScheduleResult
) -> ReplayVerificationSnapshot:
    performed = isinstance(portfolio_metadata.get("verified_feasible"), bool)
    feasible = bool(portfolio_metadata.get("verified_feasible", _result_is_feasible(result)))

    violation_count_value = portfolio_metadata.get("violation_count", 0)
    violation_count = violation_count_value if isinstance(violation_count_value, int) else 0

    violation_kinds_value = portfolio_metadata.get("violation_kinds", [])
    violation_kinds = (
        [str(item) for item in violation_kinds_value]
        if isinstance(violation_kinds_value, list)
        else []
    )

    return ReplayVerificationSnapshot(
        performed=performed,
        feasible=feasible,
        violation_count=violation_count if performed else 0,
        violation_kinds=violation_kinds if performed else [],
    )


def slugify_replay_token(value: str) -> str:
    """Return a filesystem-safe slug for replay artifact filenames."""

    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return slug.strip("._") or "artifact"


def write_replay_artifact(
    output_dir: Path,
    artifact: ReplayBenchmarkArtifact | ReplayRuntimeArtifact,
    *,
    stem_parts: Sequence[str],
) -> Path:
    """Write *artifact* to *output_dir* and return the created path."""

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = "__".join(slugify_replay_token(part) for part in stem_parts if part)
    artifact_path = output_dir / f"{stem or 'artifact'}__replay.json"
    artifact_path.write_text(
        json.dumps(artifact.model_dump(mode="json"), indent=2), encoding="utf-8"
    )

    manifest_path = output_dir / "manifest.jsonl"
    manifest_entry: dict[str, Any] = {
        "replay_artifact_version": artifact.replay_artifact_version,
        "artifact_kind": artifact.artifact_kind,
        "artifact_source": artifact.artifact_source,
        "artifact_path": str(artifact_path),
        "selected_solver_config": artifact.selected_solver_config,
        "solver_name": artifact.solver_name,
        "result_status": artifact.result_status,
    }
    if isinstance(artifact, ReplayBenchmarkArtifact):
        manifest_entry["instance_name"] = artifact.instance_name
        manifest_entry["solver_config"] = artifact.solver_config
    else:
        manifest_entry["request_id"] = artifact.request_id
        manifest_entry["solver_config"] = artifact.solver_config
    _append_manifest_entry(manifest_path, manifest_entry)

    return artifact_path


def _append_manifest_entry(manifest_path: Path, manifest_entry: dict[str, Any]) -> None:
    """Append one JSONL manifest record under an exclusive process lock."""

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a+", encoding="utf-8") as handle:
        _lock_manifest_handle(handle)
        try:
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(manifest_entry, ensure_ascii=False) + "\n")
            handle.flush()
        finally:
            _unlock_manifest_handle(handle)


def _lock_manifest_handle(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    flock = fcntl.flock  # type: ignore[attr-defined]
    lock_ex = fcntl.LOCK_EX  # type: ignore[attr-defined]
    flock(handle.fileno(), lock_ex)


def _unlock_manifest_handle(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    flock = fcntl.flock  # type: ignore[attr-defined]
    lock_un = fcntl.LOCK_UN  # type: ignore[attr-defined]
    flock(handle.fileno(), lock_un)


def build_benchmark_replay_artifact(
    *,
    instance_path: Path,
    solver_config: str,
    selected_solver_config: str,
    results: dict[str, Any],
    verification: dict[str, Any],
    statistics: dict[str, Any],
    problem_profile: dict[str, int | float | bool | str],
    portfolio_metadata: dict[str, Any] | None = None,
) -> ReplayBenchmarkArtifact:
    """Build the canonical replay artifact for one benchmark run."""

    metadata = dict(portfolio_metadata or {})
    routing_reason = metadata.get("routing_reason")
    if not isinstance(routing_reason, str) or not routing_reason:
        routing_reason = (
            "benchmark explicit solver configuration"
            if solver_config != "AUTO"
            else "benchmark portfolio auto routing"
        )

    regime = metadata.get("regime")
    if not isinstance(regime, str) or not regime:
        regime = "nominal"

    return ReplayBenchmarkArtifact(
        instance_name=instance_path.name,
        instance_path=str(instance_path),
        solver_config=solver_config,
        selected_solver_config=selected_solver_config,
        solver_name=str(results["solver_name"]),
        result_status=str(results["status"]),
        feasible=bool(results["feasible"]),
        proved_optimal=bool(results["proved_optimal"]),
        assignments=int(results["assignments"]),
        objective=ReplayObjectiveSnapshot(
            makespan_minutes=float(results["makespan_minutes"]),
            total_setup_minutes=float(results["total_setup_minutes"]),
            total_tardiness_minutes=float(results["total_tardiness_minutes"]),
            total_material_loss=float(results["total_material_loss"]),
            weighted_sum=float(results["weighted_sum"]),
        ),
        verification=ReplayVerificationSnapshot(
            performed=True,
            feasible=bool(verification["feasible"]),
            violation_count=int(verification["violation_count"]),
            violation_kinds=list(verification["violation_kinds"]),
        ),
        statistics={
            key: value
            for key, value in statistics.items()
            if isinstance(value, int | float | bool) or value is None
        },
        problem_profile=problem_profile,
        routing=ReplayRoutingSnapshot(
            execution_mode=str(metadata.get("execution_mode", "solve")),
            routed=bool(metadata.get("routed", solver_config == "AUTO")),
            routing_reason=routing_reason,
            regime=regime,
            preferred_max_latency_s=_coerce_int_or_none(metadata.get("preferred_max_latency_s")),
            exact_required=_coerce_bool_or_none(metadata.get("exact_required")),
        ),
        portfolio_metadata=metadata,
    )


def build_runtime_replay_artifact(
    *,
    artifact_kind: Literal["runtime-solve", "runtime-repair"],
    artifact_source: str,
    problem: ScheduleProblem,
    result: ScheduleResult,
    request_summary: dict[str, Any],
    request_id: str | None = None,
    solver_config: str | None = None,
) -> ReplayRuntimeArtifact:
    """Build the canonical replay artifact for one runtime solve or repair run."""

    metadata = result.metadata.get("portfolio", {})
    portfolio_metadata = dict(metadata) if isinstance(metadata, dict) else {}
    selected_solver_config = portfolio_metadata.get("solver_config")
    if not isinstance(selected_solver_config, str) or not selected_solver_config:
        selected_solver_config = solver_config or result.solver_name

    routing_reason = portfolio_metadata.get("routing_reason")
    if not isinstance(routing_reason, str) or not routing_reason:
        routing_reason = "runtime replay capture"

    regime = portfolio_metadata.get("regime")
    if not isinstance(regime, str) or not regime:
        regime = "nominal"

    return ReplayRuntimeArtifact(
        artifact_kind=artifact_kind,
        artifact_source=artifact_source,
        request_id=request_id,
        solver_config=solver_config,
        selected_solver_config=selected_solver_config,
        solver_name=result.solver_name,
        result_status=result.status.value,
        feasible=_result_is_feasible(result),
        proved_optimal=result.status is SolverStatus.OPTIMAL,
        assignments=len(result.assignments),
        objective=ReplayObjectiveSnapshot(
            makespan_minutes=result.objective.makespan_minutes,
            total_setup_minutes=result.objective.total_setup_minutes,
            total_tardiness_minutes=result.objective.total_tardiness_minutes,
            total_material_loss=result.objective.total_material_loss,
            weighted_sum=result.objective.weighted_sum,
        ),
        verification=_build_verification_snapshot(portfolio_metadata, result),
        problem_profile=build_problem_profile(problem).as_dict(),
        routing=ReplayRoutingSnapshot(
            execution_mode=str(portfolio_metadata.get("execution_mode", "solve")),
            routed=bool(portfolio_metadata.get("routed", False)),
            routing_reason=routing_reason,
            regime=regime,
            preferred_max_latency_s=_coerce_int_or_none(
                portfolio_metadata.get("preferred_max_latency_s")
            ),
            exact_required=_coerce_bool_or_none(portfolio_metadata.get("exact_required")),
        ),
        request_summary=request_summary,
        portfolio_metadata=portfolio_metadata,
    )


__all__ = [
    "REPLAY_ARTIFACT_VERSION",
    "ReplayBenchmarkArtifact",
    "ReplayObjectiveSnapshot",
    "ReplayRoutingSnapshot",
    "ReplayRuntimeArtifact",
    "ReplayVerificationSnapshot",
    "build_benchmark_replay_artifact",
    "build_runtime_replay_artifact",
    "slugify_replay_token",
    "write_replay_artifact",
]
