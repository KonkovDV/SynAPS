"""Tests for the W-A commit-time precedence gate (temporal closure)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import Assignment, Operation
from synaps.solvers.rhc import RhcSolver
from synaps.solvers.rhc._policy import RhcPolicy, RhcPolicySpec, build_solve_kwargs_from_spec
from synaps.solvers.rhc._window import filter_commit_candidates_by_precedence

T0 = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)


def _op(order_id, seq, pred=None):
    return Operation(
        order_id=order_id,
        seq_in_order=seq,
        state_id=uuid4(),
        base_duration_min=10,
        eligible_wc_ids=[],
        predecessor_op_id=pred,
    )


def _assignment(op_id, start_min, end_min, wc_id=None):
    return Assignment(
        operation_id=op_id,
        work_center_id=wc_id or uuid4(),
        start_time=T0 + timedelta(minutes=start_min),
        end_time=T0 + timedelta(minutes=end_min),
    )


class TestFilterCommitCandidatesByPrecedence:
    def test_keeps_temporally_consistent_chain(self) -> None:
        order = uuid4()
        a = _op(order, 1)
        b = _op(order, 2, pred=a.id)
        ops = {a.id: a, b.id: b}
        candidates = {
            a.id: _assignment(a.id, 0, 10),
            b.id: _assignment(b.id, 10, 20),
        }
        kept, deferred = filter_commit_candidates_by_precedence(
            candidates, committed_assignment_by_op={}, ops_by_id=ops
        )
        assert set(kept) == {a.id, b.id}
        assert deferred == set()

    def test_defers_successor_starting_before_predecessor_ends(self) -> None:
        order = uuid4()
        a = _op(order, 1)
        b = _op(order, 2, pred=a.id)
        ops = {a.id: a, b.id: b}
        candidates = {
            a.id: _assignment(a.id, 0, 30),
            b.id: _assignment(b.id, 20, 40),  # starts before pred ends
        }
        kept, deferred = filter_commit_candidates_by_precedence(
            candidates, committed_assignment_by_op={}, ops_by_id=ops
        )
        assert set(kept) == {a.id}
        assert deferred == {b.id}

    def test_defers_against_frozen_committed_predecessor(self) -> None:
        order = uuid4()
        a = _op(order, 1)
        b = _op(order, 2, pred=a.id)
        ops = {a.id: a, b.id: b}
        committed = {a.id: _assignment(a.id, 0, 50)}
        candidates = {b.id: _assignment(b.id, 40, 60)}  # frozen pred ends at 50
        kept, deferred = filter_commit_candidates_by_precedence(
            candidates, committed_assignment_by_op=committed, ops_by_id=ops
        )
        assert kept == {}
        assert deferred == {b.id}

    def test_deferral_cascades_through_co_committed_chain(self) -> None:
        order = uuid4()
        a = _op(order, 1)
        b = _op(order, 2, pred=a.id)
        c = _op(order, 3, pred=b.id)
        ops = {a.id: a, b.id: b, c.id: c}
        candidates = {
            a.id: _assignment(a.id, 0, 30),
            b.id: _assignment(b.id, 20, 40),  # violates → deferred
            c.id: _assignment(c.id, 40, 50),  # temporally fine but pred deferred
        }
        kept, deferred = filter_commit_candidates_by_precedence(
            candidates, committed_assignment_by_op={}, ops_by_id=ops
        )
        assert set(kept) == {a.id}
        assert deferred == {b.id, c.id}

    def test_defers_when_predecessor_unplaced(self) -> None:
        order = uuid4()
        a = _op(order, 1)
        b = _op(order, 2, pred=a.id)
        ops = {a.id: a, b.id: b}
        candidates = {b.id: _assignment(b.id, 0, 10)}
        kept, deferred = filter_commit_candidates_by_precedence(
            candidates, committed_assignment_by_op={}, ops_by_id=ops
        )
        assert kept == {}
        assert deferred == {b.id}

    def test_no_predecessor_always_kept(self) -> None:
        a = _op(uuid4(), 1)
        candidates = {a.id: _assignment(a.id, 0, 10)}
        kept, deferred = filter_commit_candidates_by_precedence(
            candidates, committed_assignment_by_op={}, ops_by_id={a.id: a}
        )
        assert set(kept) == {a.id}
        assert deferred == set()


class TestRhcGateIntegration:
    def test_gate_disabled_by_default_with_metadata(self) -> None:
        from tests.conftest import make_simple_problem

        problem = make_simple_problem(n_orders=2, ops_per_order=2)
        result = RhcSolver().solve(
            problem,
            inner_solver="greedy",
            time_limit_s=30,
            window_minutes=240,
            overlap_minutes=60,
        )
        assert result.metadata["commit_precedence_gate_enabled"] is False
        assert result.metadata["commit_precedence_deferred_ops_total"] == 0

    def test_search_cover_preset_enables_gate(self) -> None:
        kwargs = build_solve_kwargs_from_spec(RhcPolicySpec.from_preset(RhcPolicy.SEARCH_COVER))
        assert kwargs["commit_precedence_gate_enabled"] is True

    def test_other_presets_keep_gate_disabled(self) -> None:
        for policy in (RhcPolicy.BALANCED, RhcPolicy.GREEDY_COVER, RhcPolicy.FAST_50K):
            kwargs = build_solve_kwargs_from_spec(RhcPolicySpec.from_preset(policy))
            assert kwargs["commit_precedence_gate_enabled"] is False, policy

    def test_rhc_greedy_cover_registry_keeps_gate_off(self) -> None:
        from synaps.solvers.registry import create_solver

        _, kwargs = create_solver("RHC-GREEDY-COVER")
        assert kwargs["commit_precedence_gate_enabled"] is False

    def test_forced_global_list_schedule_has_zero_precedence_violations(self) -> None:
        """Global list-schedule is one pass; no window commit, so the gate is unused.

        Cross-window PRECEDENCE_VIOLATION cannot arise because there are no
        frozen windows. This is the ≥10k COVER path, forced here with min_ops=0.
        """
        from synaps.solvers.feasibility_checker import FeasibilityChecker
        from synaps.solvers.registry import create_solver
        from tests.conftest import make_simple_problem

        problem = make_simple_problem(n_orders=4, ops_per_order=3)
        solver, kwargs = create_solver("RHC-GREEDY-COVER")
        kwargs["global_greedy_cover_min_ops"] = 0
        kwargs["time_limit_s"] = 30
        result = solver.solve(problem, **kwargs)
        assert result.metadata["global_greedy_cover"] is True
        assert result.metadata["commit_precedence_gate_enabled"] is False
        violations = FeasibilityChecker().check(problem, result.assignments, exhaustive=True)
        precedence = [item for item in violations if item.kind == "PRECEDENCE_VIOLATION"]
        assert precedence == [], [item.message for item in precedence]


@pytest.mark.slow
class TestGateEliminatesPrecedenceViolations:
    def test_industrial_seed42_zero_precedence_violations(self) -> None:
        """Integration: gate=on removes PRECEDENCE_VIOLATION on industrial/seed42.

        Pre-gate evidence (BENCHMARK_EVIDENCE_SEARCH_COVER_2026_07_29.md §3):
        20 precedence violations at this preset/seed/budget.
        """
        from benchmark.generate_instances import generate_problem, preset_spec
        from synaps.solvers.feasibility_checker import FeasibilityChecker

        problem = generate_problem(preset_spec("industrial", seed=42))
        kwargs = build_solve_kwargs_from_spec(RhcPolicySpec.from_preset(RhcPolicy.SEARCH_COVER))
        kwargs["time_limit_s"] = 45
        result = RhcSolver().solve(problem, **kwargs)
        violations = FeasibilityChecker().check(problem, result.assignments)
        precedence = [v for v in violations if v.kind == "PRECEDENCE_VIOLATION"]
        assert precedence == [], f"{len(precedence)} precedence violations with gate on"
        # Coverage must not collapse: residual fill re-places deferred ops.
        scheduled_ratio = result.metadata["ops_scheduled"] / result.metadata["ops_total"]
        assert scheduled_ratio >= 0.95
