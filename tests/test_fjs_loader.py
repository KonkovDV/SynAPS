"""Tests for the standard .fjs public-benchmark loader (W3)."""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from benchmark.fjs_loader import FjsParseError, describe_fjs_mapping, load_fjs_problem
from benchmark.run_benchmark import load_problem
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch

# Synthetic 2-job / 3-machine instance in the standard format:
#   J1: op1 {M1:3 | M2:5}, op2 {M2:4}
#   J2: op1 {M3:2}, op2 {M1:6 | M3:3}, op3 {M2:1}
SYNTHETIC_FJS = """\
2 3 1.6
2 2 1 3 2 5 1 2 4
3 1 3 2 2 1 6 3 3 1 2 1
"""


@pytest.fixture
def fjs_path(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic_2x3.fjs"
    path.write_text(SYNTHETIC_FJS, encoding="utf-8")
    return path


class TestFjsParsing:
    def test_parses_structure(self, fjs_path: Path) -> None:
        problem = load_fjs_problem(fjs_path)
        assert len(problem.orders) == 2
        assert len(problem.operations) == 5
        assert len(problem.work_centers) == 3
        assert problem.setup_matrix == []
        assert len(problem.states) == 1

    def test_min_duration_and_eligibility_mapping(self, fjs_path: Path) -> None:
        problem = load_fjs_problem(fjs_path)
        wc_code_by_id = {wc.id: wc.code for wc in problem.work_centers}
        ops_j1 = sorted(
            (op for op in problem.operations if op.seq_in_order in (1, 2)),
            key=lambda op: op.seq_in_order,
        )
        first = next(
            op
            for op in problem.operations
            if op.seq_in_order == 1 and len(op.eligible_wc_ids) == 2
        )
        # J1 op1: alternatives M1:3, M2:5 → base = 3, eligible {M1, M2}.
        assert first.base_duration_min == 3
        assert {wc_code_by_id[wc_id] for wc_id in first.eligible_wc_ids} == {"M1", "M2"}
        assert first.domain_attributes["fjs_machine_durations"] == {"M1": 3, "M2": 5}
        assert ops_j1  # precedence chain sanity below

    def test_precedence_chain_within_jobs(self, fjs_path: Path) -> None:
        problem = load_fjs_problem(fjs_path)
        by_order: dict[object, list[object]] = {}
        for op in problem.operations:
            by_order.setdefault(op.order_id, []).append(op)
        for ops in by_order.values():
            ops_sorted = sorted(ops, key=lambda o: o.seq_in_order)  # type: ignore[attr-defined]
            assert ops_sorted[0].predecessor_op_id is None  # type: ignore[attr-defined]
            for prev, curr in pairwise(ops_sorted):
                assert curr.predecessor_op_id == prev.id  # type: ignore[attr-defined]

    def test_due_dates_equal_horizon_end(self, fjs_path: Path) -> None:
        problem = load_fjs_problem(fjs_path)
        for order in problem.orders:
            assert order.due_date == problem.planning_horizon_end

    def test_run_benchmark_load_problem_dispatches_fjs(self, fjs_path: Path) -> None:
        problem = load_problem(fjs_path)
        assert len(problem.operations) == 5

    def test_greedy_solves_loaded_instance_feasibly(self, fjs_path: Path) -> None:
        problem = load_fjs_problem(fjs_path)
        result = GreedyDispatch().solve(problem)
        assert result.status.value in ("optimal", "feasible")
        assert len(result.assignments) == 5
        violations = FeasibilityChecker().check(problem, result.assignments)
        assert violations == []

    def test_mapping_description_mentions_comparability(self) -> None:
        mapping = describe_fjs_mapping()
        assert "not directly comparable" in mapping["comparability_note"].lower()


class TestFjsErrors:
    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.fjs"
        path.write_text("", encoding="utf-8")
        with pytest.raises(FjsParseError, match="empty"):
            load_fjs_problem(path)

    def test_truncated_body(self, tmp_path: Path) -> None:
        path = tmp_path / "trunc.fjs"
        path.write_text("1 2\n2 1 1 5 1", encoding="utf-8")
        with pytest.raises(FjsParseError, match="unexpected end of file"):
            load_fjs_problem(path)

    def test_machine_out_of_range(self, tmp_path: Path) -> None:
        path = tmp_path / "badmachine.fjs"
        path.write_text("1 2\n1 1 3 5", encoding="utf-8")
        with pytest.raises(FjsParseError, match="out of range"):
            load_fjs_problem(path)

    def test_trailing_tokens(self, tmp_path: Path) -> None:
        path = tmp_path / "trailing.fjs"
        path.write_text("1 2\n1 1 1 5 99 99", encoding="utf-8")
        with pytest.raises(FjsParseError, match="trailing tokens"):
            load_fjs_problem(path)

    def test_non_numeric_token(self, tmp_path: Path) -> None:
        path = tmp_path / "alpha.fjs"
        path.write_text("1 x\n1 1 1 5", encoding="utf-8")
        with pytest.raises(FjsParseError, match="non-numeric"):
            load_fjs_problem(path)

    def test_infinity_token_rejected(self, tmp_path: Path) -> None:
        # float("inf") succeeds but int(inf) raises OverflowError — must be
        # surfaced as a parse error, not an uncaught crash.
        path = tmp_path / "inf.fjs"
        path.write_text("1 2\n1 1 1 inf", encoding="utf-8")
        with pytest.raises(FjsParseError, match="non-numeric"):
            load_fjs_problem(path)

    def test_oversized_duration_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "huge.fjs"
        path.write_text("1 2\n1 1 1 999999999999999", encoding="utf-8")
        with pytest.raises(FjsParseError, match="sanity limit"):
            load_fjs_problem(path)
