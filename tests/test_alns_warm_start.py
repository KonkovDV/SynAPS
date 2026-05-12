"""Unit tests for ALNS warm-start wiring (Stage C1, Task 9.4).

Verifies that the ALNS solver accepts `warm_start_assignments` via kwargs,
uses it as the initial solution (skipping greedy when full coverage is
possible), and reports the new `alns_warm_start_used` /
`alns_warm_start_coverage` metadata fields.

Validates: Requirements 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    ScheduleResult,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import AlnsSolver
from synaps.solvers.greedy_dispatch import GreedyDispatch


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 3, 20, 0, tzinfo=UTC)


def _make_small_feasible_problem(
    n_orders: int = 5,
    ops_per_order: int = 3,
    n_machines: int = 3,
    seed: int = 42,
) -> ScheduleProblem:
    """Build a small deterministic FJSP-SDST problem (~15 ops, 3 machines)."""
    rng = random.Random(seed)

    states = [State(id=uuid4(), code=f"S{i}", label=f"State {i}") for i in range(3)]
    state_ids = [s.id for s in states]

    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"M{i}",
            capability_group="grp",
            speed_factor=round(0.8 + rng.random() * 0.4, 2),
        )
        for i in range(n_machines)
    ]
    wc_ids = [wc.id for wc in work_centers]

    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if rng.random() < 0.7:
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=rng.randint(5, 25),
                        )
                    )

    orders: list[Order] = []
    operations: list[Operation] = []

    for i in range(n_orders):
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{i:04d}",
                due_date=HORIZON_START + timedelta(hours=8 + i * 4),
                priority=500 + i * 100,
            )
        )
        prev_op_id: UUID | None = None
        for j in range(ops_per_order):
            op_id = uuid4()
            n_eligible = rng.randint(2, n_machines)
            eligible = rng.sample(wc_ids, n_eligible)
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=rng.choice(state_ids),
                    base_duration_min=rng.randint(15, 60),
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


def _greedy_warm_start(problem: ScheduleProblem) -> list[Assignment]:
    """Produce a full, feasible warm-start set via the greedy dispatch heuristic."""
    result = GreedyDispatch().solve(problem, time_limit_s=10.0)
    assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
        f"Greedy dispatch did not produce a feasible seed: status={result.status}"
    )
    assert len(result.assignments) == len(problem.operations), (
        "Greedy dispatch did not cover every operation; cannot use as full warm-start."
    )
    return list(result.assignments)


def _solve_alns(
    problem: ScheduleProblem,
    *,
    warm_start_assignments: list[Assignment] | None,
    max_iterations: int = 20,
    time_limit_s: float = 30.0,
) -> ScheduleResult:
    """Helper to solve ALNS with tight bounds (small instance)."""
    solver = AlnsSolver()
    kwargs: dict = {
        "max_iterations": max_iterations,
        "time_limit_s": time_limit_s,
        "destroy_fraction": 0.2,
        "min_destroy": 2,
        "max_destroy": 5,
        "repair_time_limit_s": 5,
    }
    if warm_start_assignments is not None:
        kwargs["warm_start_assignments"] = warm_start_assignments
    return solver.solve(problem, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAlnsWarmStartMetadata:
    """Task 9.4: verify warm-start metadata reported by ALNS solver."""

    def test_no_warm_start_runs_greedy_and_reports_zero_coverage(self) -> None:
        """Test 1: passing `warm_start_assignments=None` → greedy runs,
        `alns_warm_start_used=False`, `alns_warm_start_coverage=0.0`.
        """
        problem = _make_small_feasible_problem(
            n_orders=5, ops_per_order=3, n_machines=3, seed=42
        )
        result = _solve_alns(problem, warm_start_assignments=None)

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
            f"Expected FEASIBLE/OPTIMAL, got {result.status}"
        )
        md = result.metadata

        assert md["alns_warm_start_used"] is False, (
            f"alns_warm_start_used must be False when no warm-start supplied, "
            f"got {md.get('alns_warm_start_used')}"
        )
        assert md["alns_warm_start_coverage"] == pytest.approx(0.0, abs=1e-9), (
            f"alns_warm_start_coverage must be 0.0 when no warm-start supplied, "
            f"got {md.get('alns_warm_start_coverage')}"
        )
        assert md["warm_start_supplied_assignments"] == 0
        assert md["warm_start_completed_assignments"] == 0
        # Initial solver should be the greedy/beam path, never warm_start.
        assert md["initial_solver"] != "warm_start"

    def test_full_warm_start_skips_greedy_and_reports_full_coverage(self) -> None:
        """Test 2: passing a full warm-start covering all ops → greedy is
        skipped, `alns_warm_start_used=True`, `alns_warm_start_coverage=1.0`,
        and the initial seed is the warm start itself.
        """
        problem = _make_small_feasible_problem(
            n_orders=5, ops_per_order=3, n_machines=3, seed=42
        )
        warm = _greedy_warm_start(problem)
        # Sanity: full coverage of every operation.
        assert len(warm) == len(problem.operations)

        # Use zero iterations to isolate the initial-solution phase so we can
        # observe the warm-start seed before ALNS mutates it.
        result = _solve_alns(
            problem,
            warm_start_assignments=warm,
            max_iterations=0,
            time_limit_s=30.0,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
            f"Expected FEASIBLE/OPTIMAL, got {result.status}"
        )
        md = result.metadata

        assert md["alns_warm_start_used"] is True, (
            "alns_warm_start_used must be True when a full warm-start is consumed"
        )
        assert md["alns_warm_start_coverage"] == pytest.approx(1.0, abs=1e-9), (
            f"alns_warm_start_coverage must be 1.0 for full coverage, "
            f"got {md.get('alns_warm_start_coverage')}"
        )
        assert md["warm_start_supplied_assignments"] == len(problem.operations)
        # No greedy fill needed when warm-start already covers every op.
        assert md["warm_start_completed_assignments"] == 0
        assert md["initial_solver"] == "warm_start"
        # Warm-start was consumed, so no rejection reason should be recorded.
        assert md["warm_start_rejected_reason"] is None

        # With 0 iterations, the final makespan equals the warm-start makespan
        # (ALNS never got a chance to mutate it).
        warm_makespan = max(
            (a.end_time - problem.planning_horizon_start).total_seconds() / 60.0
            for a in warm
        )
        assert result.objective.makespan_minutes == pytest.approx(
            warm_makespan, abs=1e-6
        )

    def test_partial_warm_start_reports_fractional_coverage(self) -> None:
        """Test 3: passing a partial warm-start (subset of ops) →
        `alns_warm_start_used=True`, `alns_warm_start_coverage` in (0.0, 1.0).
        Greedy fills the remaining operations.
        """
        problem = _make_small_feasible_problem(
            n_orders=5, ops_per_order=3, n_machines=3, seed=42
        )
        warm_full = _greedy_warm_start(problem)
        n_ops = len(problem.operations)

        # Take a prefix that covers *complete* order chains so the greedy
        # filler can legally repair the remaining operations (precedence-safe
        # split). We pick the first 2 orders' assignments.
        first_two_order_ids = {o.id for o in problem.orders[:2]}
        partial_op_ids = {
            op.id for op in problem.operations if op.order_id in first_two_order_ids
        }
        warm_partial = [a for a in warm_full if a.operation_id in partial_op_ids]
        assert 0 < len(warm_partial) < n_ops, (
            "Partial warm-start must be a strict subset for this test."
        )

        result = _solve_alns(
            problem,
            warm_start_assignments=warm_partial,
            max_iterations=0,
            time_limit_s=30.0,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
            f"Expected FEASIBLE/OPTIMAL, got {result.status}"
        )
        md = result.metadata

        # The solver succeeds either by completing the partial warm-start with
        # greedy fill (preferred path) OR by ignoring the partial seed and
        # falling back to a full greedy solve. Both behaviors are acceptable
        # per Task 9.4; the telemetry must reflect which path ran.
        supplied = md["warm_start_supplied_assignments"]
        assert supplied == len(warm_partial), (
            f"warm_start_supplied_assignments ({supplied}) must equal the "
            f"size of the partial warm-start ({len(warm_partial)})."
        )

        expected_coverage = round(len(warm_partial) / n_ops, 6)
        assert md["alns_warm_start_coverage"] == pytest.approx(
            expected_coverage, abs=1e-6
        ), (
            f"alns_warm_start_coverage should equal supplied/n_ops = "
            f"{expected_coverage}, got {md['alns_warm_start_coverage']}"
        )
        assert 0.0 < md["alns_warm_start_coverage"] < 1.0

        if md["alns_warm_start_used"]:
            # Partial warm-start path succeeded: greedy must have filled the gap.
            assert md["warm_start_completed_assignments"] > 0, (
                "Partial warm-start was consumed but no greedy completion is "
                "recorded."
            )
            assert (
                md["warm_start_supplied_assignments"]
                + md["warm_start_completed_assignments"]
                == n_ops
            )
            assert md["initial_solver"] == "warm_start"
        else:
            # Fallback path: greedy ran for the entire instance.
            assert md["initial_solver"] != "warm_start"
            assert md["warm_start_rejected_reason"] is not None

    def test_invalid_warm_start_rejected_or_partial(self) -> None:
        """Test 4: an invalid warm-start (wrong work_center_id for an
        operation, making the assignment infeasible) must not crash the
        solver. The solver either:
          - rejects the warm-start entirely (falls back to greedy), or
          - treats it as partial and repairs with greedy fill.

        In both cases the solver must return a feasible schedule and the
        telemetry must truthfully reflect which path ran.
        """
        problem = _make_small_feasible_problem(
            n_orders=5, ops_per_order=3, n_machines=3, seed=42
        )
        warm_full = _greedy_warm_start(problem)

        # Corrupt one assignment by pointing it at a work center the operation
        # is not eligible for. Find one op whose eligible set is a strict
        # subset of available machines.
        wc_ids_all = [wc.id for wc in problem.work_centers]
        corrupt_idx: int | None = None
        bad_wc_id: UUID | None = None
        for idx, a in enumerate(warm_full):
            op = next(o for o in problem.operations if o.id == a.operation_id)
            ineligible = [wc for wc in wc_ids_all if wc not in op.eligible_wc_ids]
            if ineligible:
                corrupt_idx = idx
                bad_wc_id = ineligible[0]
                break

        assert corrupt_idx is not None and bad_wc_id is not None, (
            "Test fixture did not produce an operation with a restrictive "
            "eligibility set; cannot craft an invalid warm-start."
        )

        warm_invalid = list(warm_full)
        bad = warm_invalid[corrupt_idx]
        warm_invalid[corrupt_idx] = Assignment(
            operation_id=bad.operation_id,
            work_center_id=bad_wc_id,
            start_time=bad.start_time,
            end_time=bad.end_time,
            setup_minutes=bad.setup_minutes,
            aux_resource_ids=list(bad.aux_resource_ids),
            lane_id=bad.lane_id,
        )

        result = _solve_alns(
            problem,
            warm_start_assignments=warm_invalid,
            max_iterations=20,
            time_limit_s=30.0,
        )

        # The solver must still return a usable result (not ERROR); if it
        # rejects warm-start it falls back to greedy for the full instance.
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
            f"Invalid warm-start must not produce ERROR status, got {result.status}"
        )
        md = result.metadata

        # Supplied count still reflects the caller-supplied size; coverage is
        # driven by what the caller provided, not by whether it was consumed.
        assert md["warm_start_supplied_assignments"] == len(warm_invalid)
        assert md["alns_warm_start_coverage"] == pytest.approx(
            round(len(warm_invalid) / len(problem.operations), 6),
            abs=1e-6,
        )

        if md["alns_warm_start_used"]:
            # The ALNS main loop may have already repaired the invalid seed
            # via destroy/repair. In that case the solver reports the warm
            # start as used and `warm_start_rejected_reason` should be None.
            assert md["warm_start_rejected_reason"] is None
        else:
            # Fallback path: the warm-start was rejected for being infeasible.
            # A rejection reason must be recorded so callers can diagnose why.
            assert md["warm_start_rejected_reason"] is not None, (
                "When an invalid warm-start is rejected, "
                "`warm_start_rejected_reason` must be populated."
            )
            assert md["initial_solver"] != "warm_start"
