"""Regression tests for Phase 2 LBBD upgrades."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    Assignment,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers._lbbd_cuts import (
    compute_machine_transition_floor as _compute_machine_transition_floor_plain,
    compute_machine_tsp_lower_bound as _compute_machine_tsp_lb_plain,
    compute_sequence_independent_setup_lower_bound as _compute_setup_lb_plain,
    # Parity check aliases — same underlying helpers, ensure both solvers share logic
    compute_machine_transition_floor as _compute_machine_transition_floor_hd,
    compute_sequence_independent_setup_lower_bound as _compute_setup_lb_hd,
)
from synaps.solvers.lbbd_hd_solver import LbbdHdSolver
from synaps.solvers.lbbd_solver import LbbdSolver

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)


def _make_setup_dense_problem() -> ScheduleProblem:
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    work_center = WorkCenter(
        id=uuid4(),
        code="WC-SETUP",
        capability_group="machining",
        speed_factor=1.0,
    )

    orders: list[Order] = []
    operations: list[Operation] = []
    for index in range(4):
        order = Order(
            id=uuid4(),
            external_ref=f"ORD-{index}",
            due_date=HORIZON_START + timedelta(hours=8),
        )
        orders.append(order)
        operations.append(
            Operation(
                id=uuid4(),
                order_id=order.id,
                seq_in_order=0,
                state_id=state_a.id if index % 2 == 0 else state_b.id,
                base_duration_min=20,
                eligible_wc_ids=[work_center.id],
            )
        )

    setup_matrix = [
        SetupEntry(
            work_center_id=work_center.id,
            from_state_id=state_a.id,
            to_state_id=state_b.id,
            setup_minutes=5,
        ),
        SetupEntry(
            work_center_id=work_center.id,
            from_state_id=state_b.id,
            to_state_id=state_a.id,
            setup_minutes=5,
        ),
    ]

    return ScheduleProblem(
        states=[state_a, state_b],
        orders=orders,
        operations=operations,
        work_centers=[work_center],
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


def test_machine_tsp_cut_replaces_setup_cost_for_small_state_pools() -> None:
    """Standard LBBD should prefer the sequence-aware machine_tsp cut over the
    sequence-independent setup_cost floor when the realised distinct state
    count fits Bellman-Held-Karp (≤12 by default).
    """
    problem = _make_setup_dense_problem()

    result = LbbdSolver().solve(
        problem,
        max_iterations=4,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )

    assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    cut_kinds = result.metadata["cut_pool"]["kinds"]
    # setup_cost is the legacy floor; machine_tsp is the dominating Naderi &
    # Roshanaei (2021) cut. On small state pools the latter must be active and
    # the former must not be emitted (machine_tsp dominates and short-circuits
    # the sequence-independent fallback in the same iteration).
    assert cut_kinds.get("machine_tsp", 0) >= 1
    assert cut_kinds.get("setup_cost", 0) == 0
    assert cut_kinds.get("critical_path", 0) >= 1


def test_machine_tsp_lower_bound_dominates_sequence_independent_floor() -> None:
    """For any realised state set within the Bellman-Held-Karp window, the
    machine-TSP setup bound must be at least as tight as the sequence-
    independent floor used by the legacy setup_cost cut.
    """
    problem = _make_setup_dense_problem()
    work_center = problem.work_centers[0]
    ops_by_id = {operation.id: operation for operation in problem.operations}
    assignments = [
        Assignment(
            operation_id=operation.id,
            work_center_id=work_center.id,
            start_time=HORIZON_START + timedelta(minutes=index * 25),
            end_time=HORIZON_START + timedelta(minutes=index * 25 + 20),
        )
        for index, operation in enumerate(problem.operations)
    ]
    setup_lookup = {
        (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
        for entry in problem.setup_matrix
    }
    state_seq = [
        ops_by_id[assignment.operation_id].state_id for assignment in assignments
    ]

    tsp_bound = _compute_machine_tsp_lb_plain(state_seq, work_center.id, setup_lookup)
    seq_independent_bound = _compute_setup_lb_plain(
        assignments, work_center.id, ops_by_id, setup_lookup
    )

    assert tsp_bound >= seq_independent_bound
    # On A↔B↔A with sdst = 5 in both directions, BHK yields exactly one
    # transition's worth of setup (the path is A→B with cost 5 or B→A with
    # cost 5), matching the legacy floor of 5.0 for two distinct states.
    assert tsp_bound == 5.0


def test_machine_tsp_lower_bound_returns_zero_above_max_states() -> None:
    """machine_tsp bound must short-circuit to 0.0 when the distinct state
    count exceeds the Bellman-Held-Karp ceiling, so the caller can fall back
    to the sequence-independent floor.
    """
    work_center_id = uuid4()
    state_ids = [uuid4() for _ in range(13)]
    setup_lookup: dict[tuple, float] = {}
    for from_state in state_ids:
        for to_state in state_ids:
            if from_state != to_state:
                setup_lookup[(work_center_id, from_state, to_state)] = 5.0

    bound = _compute_machine_tsp_lb_plain(state_ids, work_center_id, setup_lookup)

    assert bound == 0.0


def test_lbbd_metadata_exposes_lb_evolution_and_cut_kind_contribution() -> None:
    """Master-LB telemetry must surface the per-iteration LB trajectory and
    the cut-kind attribution sums so reviewers can quantify which cuts
    actually moved the lower bound (arXiv 2504.16106 reporting style).
    """
    problem = _make_setup_dense_problem()

    result = LbbdSolver().solve(
        problem,
        max_iterations=6,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )

    metadata = result.metadata
    assert "lb_evolution" in metadata
    assert "cut_kind_lb_contribution" in metadata

    lb_evolution = metadata["lb_evolution"]
    assert isinstance(lb_evolution, list)
    assert len(lb_evolution) == metadata["iterations"]
    assert all(isinstance(value, (int, float)) for value in lb_evolution)
    # LB cannot strictly decrease across iterations: each new master is
    # solved with at least as many cuts as the previous one.
    for previous_lb, next_lb in zip(lb_evolution, lb_evolution[1:]):
        assert next_lb + 1e-6 >= previous_lb

    contribution = metadata["cut_kind_lb_contribution"]
    assert isinstance(contribution, dict)
    # Every reported contribution key must come from the cut pool, the
    # synthetic master_relaxation source, or be a known cut kind.
    valid_kinds = set(metadata["cut_pool"]["kinds"]) | {"master_relaxation"}
    assert set(contribution).issubset(valid_kinds)
    assert all(value >= 0.0 for value in contribution.values())

    # Per-iteration entries must record the new attribution fields too.
    for entry in metadata["iteration_log"]:
        assert "lb_delta" in entry
        assert "cut_kinds_attributed" in entry
        assert isinstance(entry["cut_kinds_attributed"], list)


def test_lbbd_hd_emits_machine_tsp_cut_for_small_state_pools() -> None:
    """R1 (2026-05-03): LBBD-HD must prefer the sequence-aware machine_tsp
    Bellman-Held-Karp cut over the legacy setup_cost floor on the same
    A<->B sdst-dense fixture used by the standard LBBD regression. This is
    the cross-solver parity check that ensures the two LBBD variants share
    the same cut taxonomy.
    """
    problem = _make_setup_dense_problem()

    result = LbbdHdSolver().solve(
        problem,
        max_iterations=4,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )

    assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    cut_kinds = result.metadata["cut_pool"]["kinds"]
    assert cut_kinds.get("machine_tsp", 0) >= 1
    assert cut_kinds.get("setup_cost", 0) == 0


def test_lbbd_hd_metadata_exposes_master_lb_telemetry() -> None:
    """R10 (2026-05-03): LBBD-HD now mirrors the standard LBBD's master-LB
    telemetry contract — `lb_evolution`, `cut_kind_lb_contribution`, and
    per-iteration `lb_delta` / `cut_kinds_attributed` must all be present.
    """
    problem = _make_setup_dense_problem()

    result = LbbdHdSolver().solve(
        problem,
        max_iterations=6,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )

    metadata = result.metadata
    lb_evolution = metadata["lb_evolution"]
    assert isinstance(lb_evolution, list)
    assert len(lb_evolution) == metadata["iterations"]
    for previous_lb, next_lb in zip(lb_evolution, lb_evolution[1:]):
        assert next_lb + 1e-6 >= previous_lb

    contribution = metadata["cut_kind_lb_contribution"]
    assert isinstance(contribution, dict)
    valid_kinds = set(metadata["cut_pool"]["kinds"]) | {"master_relaxation"}
    assert set(contribution).issubset(valid_kinds)
    assert all(value >= 0.0 for value in contribution.values())

    for entry in metadata["iteration_log"]:
        assert "lb_delta" in entry
        assert "cut_kinds_attributed" in entry
        assert isinstance(entry["cut_kinds_attributed"], list)


def test_lbbd_reports_skipped_duplicate_cuts_metadata() -> None:
    """R3 (2026-05-03): the cut pool deduplication counter must be present
    in metadata regardless of whether duplicates were observed on this run.
    """
    problem = _make_setup_dense_problem()

    plain = LbbdSolver().solve(
        problem,
        max_iterations=4,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )
    hd = LbbdHdSolver().solve(
        problem,
        max_iterations=4,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )

    assert "skipped_duplicate" in plain.metadata["cut_pool"]
    assert isinstance(plain.metadata["cut_pool"]["skipped_duplicate"], int)
    assert plain.metadata["cut_pool"]["skipped_duplicate"] >= 0

    assert "skipped_duplicate" in hd.metadata["cut_pool"]
    assert isinstance(hd.metadata["cut_pool"]["skipped_duplicate"], int)
    assert hd.metadata["cut_pool"]["skipped_duplicate"] >= 0


def test_lbbd_reports_master_warm_start_iterations() -> None:
    problem = _make_setup_dense_problem()

    result = LbbdSolver().solve(
        problem,
        max_iterations=4,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )

    assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    assert result.metadata["master_warm_start_iterations"] >= 1


def test_gap_threshold_is_configurable(simple_problem: ScheduleProblem) -> None:
    solver = LbbdSolver()

    loose = solver.solve(
        simple_problem,
        max_iterations=6,
        time_limit_s=20,
        random_seed=42,
        gap_threshold=0.50,
    )
    tight = solver.solve(
        simple_problem,
        max_iterations=6,
        time_limit_s=20,
        random_seed=42,
        gap_threshold=0.01,
    )

    assert loose.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    assert tight.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    assert loose.metadata["gap_threshold"] == 0.50
    assert tight.metadata["gap_threshold"] == 0.01
    assert loose.metadata["iterations"] <= tight.metadata["iterations"]


def test_setup_relaxation_floor_drops_to_zero_when_zero_transition_exists() -> None:
    problem = _make_setup_dense_problem()
    work_center = problem.work_centers[0]
    eligible_by_op = {operation.id: list(operation.eligible_wc_ids) for operation in problem.operations}
    setup_lookup = {
        (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
        for entry in problem.setup_matrix
    }

    assert _compute_machine_transition_floor_plain(problem, eligible_by_op, work_center.id, setup_lookup) == 0.0
    assert _compute_machine_transition_floor_hd(problem, eligible_by_op, work_center.id, setup_lookup) == 0.0


def test_setup_cost_lower_bound_uses_state_mix_not_realized_sequence_cost() -> None:
    problem = _make_setup_dense_problem()
    work_center = problem.work_centers[0]
    assignments = [
        Assignment(
            operation_id=operation.id,
            work_center_id=work_center.id,
            start_time=HORIZON_START + timedelta(minutes=index * 25),
            end_time=HORIZON_START + timedelta(minutes=index * 25 + 20),
        )
        for index, operation in enumerate(problem.operations)
    ]
    ops_by_id = {operation.id: operation for operation in problem.operations}
    setup_lookup = {
        (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
        for entry in problem.setup_matrix
    }

    assert (
        _compute_setup_lb_plain(assignments, work_center.id, ops_by_id, setup_lookup) == 5.0
    )
    assert _compute_setup_lb_hd(assignments, work_center.id, ops_by_id, setup_lookup) == 5.0
