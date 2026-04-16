"""Tests for IncrementalRepair solver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.incremental_repair import IncrementalRepair
from tests.conftest import HORIZON_START

if TYPE_CHECKING:
    import pytest


class TestIncrementalRepair:
    def test_repair_maintains_feasibility(self, simple_problem: ScheduleProblem) -> None:
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        disrupted_id = simple_problem.operations[0].id

        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[disrupted_id],
            radius=3,
        )

        assert result.status == SolverStatus.FEASIBLE
        checker = FeasibilityChecker()
        violations = checker.check(simple_problem, result.assignments)
        assert violations == [], f"Violations after repair: {violations}"

    def test_repair_returns_all_operations(self, simple_problem: ScheduleProblem) -> None:
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        disrupted_id = simple_problem.operations[0].id
        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[disrupted_id],
        )

        assigned_ops = {a.operation_id for a in result.assignments}
        expected_ops = {op.id for op in simple_problem.operations}
        assert assigned_ops == expected_ops

    def test_repair_is_deterministic_for_same_inputs(self, simple_problem: ScheduleProblem) -> None:
        """IncrementalRepair should return the same schedule for identical inputs."""
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        disrupted = [simple_problem.operations[1].id, simple_problem.operations[0].id]
        repair = IncrementalRepair()

        r1 = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=disrupted,
            radius=3,
        )
        r2 = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=disrupted,
            radius=3,
        )

        assert r1.status == SolverStatus.FEASIBLE
        assert r2.status == SolverStatus.FEASIBLE

        def signature(result: ScheduleResult) -> list[tuple[str, str, int, int]]:
            return sorted(
                (
                    str(assignment.operation_id),
                    str(assignment.work_center_id),
                    int((assignment.start_time - HORIZON_START).total_seconds() / 60.0),
                    int((assignment.end_time - HORIZON_START).total_seconds() / 60.0),
                )
                for assignment in result.assignments
            )

        assert signature(r1) == signature(r2)

    def test_repair_runs_fast(self, simple_problem: ScheduleProblem) -> None:
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[simple_problem.operations[0].id],
        )

        assert result.duration_ms < 2000, f"Repair took {result.duration_ms}ms, budget is 2000ms"

    def test_error_without_base_assignments(self, simple_problem: ScheduleProblem) -> None:
        repair = IncrementalRepair()
        result = repair.solve(simple_problem)

        assert result.status == SolverStatus.ERROR

    def test_metadata_includes_counts(self, simple_problem: ScheduleProblem) -> None:
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[simple_problem.operations[0].id],
            radius=2,
        )

        assert "neighbourhood_size" in result.metadata
        assert "frozen_count" in result.metadata
        assert "repaired_count" in result.metadata

    def test_repair_respects_setup_from_last_frozen_state(
        self, simple_problem: ScheduleProblem
    ) -> None:
        op_a, op_b, op_c, op_d = simple_problem.operations
        wc_1 = simple_problem.work_centers[0].id
        wc_2 = simple_problem.work_centers[1].id
        base_assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc_1,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
                setup_minutes=0,
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc_1,
                start_time=HORIZON_START + timedelta(minutes=40),
                end_time=HORIZON_START + timedelta(minutes=80),
                setup_minutes=10,
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc_2,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
                setup_minutes=0,
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=wc_2,
                start_time=HORIZON_START + timedelta(minutes=38),
                end_time=HORIZON_START + timedelta(minutes=78),
                setup_minutes=8,
            ),
        ]

        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_assignments,
            disrupted_op_ids=[op_b.id],
            radius=0,
        )

        assert result.status == SolverStatus.FEASIBLE
        repaired_assignment = next(a for a in result.assignments if a.operation_id == op_b.id)
        assert repaired_assignment.start_time == HORIZON_START + timedelta(minutes=40)
        assert repaired_assignment.setup_minutes == 10

        checker = FeasibilityChecker()
        violations = checker.check(simple_problem, result.assignments)
        assert violations == [], f"Violations after repair: {violations}"

    def test_repair_inserts_into_gap_before_later_frozen_assignment(
        self, simple_problem: ScheduleProblem
    ) -> None:
        problem_data = simple_problem.model_dump()
        work_center_1 = simple_problem.work_centers[0].id
        problem_data["operations"][1]["eligible_wc_ids"] = [work_center_1]
        problem = ScheduleProblem.model_validate(problem_data)

        op_a, op_b, op_c, op_d = problem.operations
        work_center_2 = problem.work_centers[1].id
        base_assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=work_center_1,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
                setup_minutes=0,
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=work_center_2,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
                setup_minutes=0,
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=work_center_1,
                start_time=HORIZON_START + timedelta(minutes=80),
                end_time=HORIZON_START + timedelta(minutes=120),
                setup_minutes=0,
            ),
        ]

        repair = IncrementalRepair()
        result = repair.solve(
            problem,
            base_assignments=base_assignments,
            disrupted_op_ids=[op_b.id],
            radius=0,
        )

        assert result.status == SolverStatus.FEASIBLE
        repaired_assignment = next(a for a in result.assignments if a.operation_id == op_b.id)
        assert repaired_assignment.work_center_id == work_center_1
        assert repaired_assignment.start_time == HORIZON_START + timedelta(minutes=40)
        assert repaired_assignment.end_time == HORIZON_START + timedelta(minutes=80)

        checker = FeasibilityChecker()
        violations = checker.check(problem, result.assignments)
        assert violations == [], f"Violations after repair: {violations}"

    def test_repair_computes_nonzero_tardiness_for_tight_due_dates(self) -> None:
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=4)
        state = State(id=uuid4(), code="STATE-A", label="State A")
        wc = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")

        order = Order(
            id=uuid4(),
            external_ref="ORD-TIGHT",
            due_date=horizon_start + timedelta(minutes=20),
        )
        op = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=60,
            eligible_wc_ids=[wc.id],
        )

        problem = ScheduleProblem(
            states=[state],
            orders=[order],
            operations=[op],
            work_centers=[wc],
            setup_matrix=[],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        base = [
            Assignment(
                operation_id=op.id,
                work_center_id=wc.id,
                start_time=horizon_start,
                end_time=horizon_start + timedelta(minutes=60),
            ),
        ]

        repair = IncrementalRepair()
        result = repair.solve(
            problem,
            base_assignments=base,
            disrupted_op_ids=[op.id],
            radius=0,
        )

        assert result.status == SolverStatus.FEASIBLE
        assert result.objective.total_tardiness_minutes >= 40.0

    def test_cpsat_fallback_returns_assignments_for_remaining_ops(
        self,
        simple_problem: ScheduleProblem,
    ) -> None:
        repair = IncrementalRepair()
        remaining_op_ids = {simple_problem.operations[-1].id}

        fallback_fn = repair._cpsat_fallback
        fallback_assignments = fallback_fn(
            simple_problem,
            [],
            remaining_op_ids,
            set(),
        )

        assert fallback_assignments is not None
        assert {assignment.operation_id for assignment in fallback_assignments} == remaining_op_ids

    def test_uses_cpsat_fallback_when_constructive_dispatch_finds_no_slot(
        self,
        simple_problem: ScheduleProblem,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        base_result = GreedyDispatch().solve(simple_problem)
        disrupted_op_id = simple_problem.operations[-1].id
        preserved_assignments = [
            assignment
            for assignment in base_result.assignments
            if assignment.operation_id == disrupted_op_id
        ]

        def no_slot(*_args: Any, **_kwargs: Any) -> None:
            return None

        def preserve_fallback(
            _self: IncrementalRepair,
            _problem: ScheduleProblem,
            _frozen_assignments: list[Assignment],
            _remaining_op_ids: set[Any],
            _already_scheduled_ids: set[Any],
        ) -> list[Assignment]:
            return preserved_assignments

        monkeypatch.setattr(
            "synaps.solvers.incremental_repair.find_earliest_feasible_slot",
            no_slot,
        )
        monkeypatch.setattr(
            IncrementalRepair,
            "_cpsat_fallback",
            preserve_fallback,
        )

        result = IncrementalRepair().solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[disrupted_op_id],
            radius=1,
        )

        assert result.status == SolverStatus.FEASIBLE
        assert result.metadata["used_cpsat_fallback"] is True
        assert any(assignment.operation_id == disrupted_op_id for assignment in result.assignments)

        checker = FeasibilityChecker()
        violations = checker.check(simple_problem, result.assignments)
        assert violations == []
