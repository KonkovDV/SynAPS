from __future__ import annotations

import json

from synaps.replay import build_runtime_replay_artifact, write_replay_artifact
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.router import SolveRegime, SolverRoutingContext
from synaps import solve_schedule
from tests.conftest import make_simple_problem


def test_write_replay_artifact_appends_manifest_entries(tmp_path) -> None:
    problem = make_simple_problem()
    replay_dir = tmp_path / "replay"

    routed_result = solve_schedule(
        problem,
        context=SolverRoutingContext(regime=SolveRegime.INTERACTIVE),
    )
    greedy_result = GreedyDispatch().solve(problem)

    first = build_runtime_replay_artifact(
        artifact_kind="runtime-solve",
        artifact_source="tests.replay.first",
        problem=problem,
        result=routed_result,
        request_summary={"request_kind": "first"},
        request_id="first-request",
        solver_config=None,
    )
    second = build_runtime_replay_artifact(
        artifact_kind="runtime-solve",
        artifact_source="tests.replay.second",
        problem=problem,
        result=greedy_result,
        request_summary={"request_kind": "second"},
        request_id="second-request",
        solver_config="GREED",
    )

    first_path = write_replay_artifact(replay_dir, first, stem_parts=("first-request", "runtime-solve"))
    second_path = write_replay_artifact(replay_dir, second, stem_parts=("second-request", "runtime-solve"))

    manifest_entries = [
        json.loads(line)
        for line in (replay_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert first_path.exists()
    assert second_path.exists()
    assert len(manifest_entries) == 2
    assert manifest_entries[0]["request_id"] == "first-request"
    assert manifest_entries[1]["request_id"] == "second-request"
