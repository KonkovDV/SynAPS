"""Tests for LBBD-HD Solver (Hierarchical Decomposition) and balanced partitioning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.lbbd_hd_solver import LbbdHdSolver
from synaps.solvers.partitioning import partition_machines


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 2, 20, 0, tzinfo=UTC)


def _make_medium_problem(
    n_orders: int = 10,
    ops_per_order: int = 4,
    n_machines: int = 5,
    n_states: int = 3,
    *,
    with_aux: bool = False,
) -> ScheduleProblem:
    """Build a medium-size FJSP-SDST problem for LBBD-HD testing."""
    states = [
        State(id=uuid4(), code=f"ST-{i}", label=f"State {i}")
        for i in range(n_states)
    ]
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i}",
            capability_group="machining",
            speed_factor=1.0 + 0.05 * i,
        )
        for i in range(n_machines)
    ]

    setup_matrix: list[SetupEntry] = []
    for wc in work_centers:
        for i, s1 in enumerate(states):
            for j, s2 in enumerate(states):
                if i == j:
                    continue
                setup_matrix.append(
                    SetupEntry(
                        work_center_id=wc.id,
                        from_state_id=s1.id,
                        to_state_id=s2.id,
                        setup_minutes=5 + abs(i - j) * 3,
                    )
                )

    orders: list[Order] = []
    operations: list[Operation] = []
    aux_resources: list[AuxiliaryResource] = []
    aux_requirements: list[OperationAuxRequirement] = []

    if with_aux:
        aux_resources = [
            AuxiliaryResource(
                id=uuid4(), code="TOOL-1", resource_type="tool", pool_size=2,
            ),
            AuxiliaryResource(
                id=uuid4(), code="CREW-1", resource_type="crew", pool_size=1,
            ),
        ]

    for order_idx in range(n_orders):
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{order_idx:04d}",
                due_date=HORIZON_START + timedelta(hours=8 + order_idx),
                priority=500 + order_idx * 50,
            )
        )

        prev = None
        for op_idx in range(ops_per_order):
            op_id = uuid4()
            state = states[op_idx % n_states]
            eligible = [wc.id for wc in work_centers[:max(2, n_machines // 2)]]
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=op_idx,
                    state_id=state.id,
                    base_duration_min=15 + op_idx * 5,
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev,
                )
            )
            if with_aux and aux_resources and op_idx % 3 == 0:
                aux_requirements.append(
                    OperationAuxRequirement(
                        operation_id=op_id,
                        aux_resource_id=aux_resources[op_idx % len(aux_resources)].id,
                        quantity_needed=1,
                    )
                )
            prev = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        auxiliary_resources=aux_resources,
        aux_requirements=aux_requirements,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


# ---------------------------------------------------------------------------
# Partitioning Tests
# ---------------------------------------------------------------------------


class TestPartitioning:
    def test_empty_assignment(self) -> None:
        problem = _make_medium_problem()
        clusters = partition_machines(problem, {}, max_ops_per_cluster=200)
        assert clusters == []

    def test_single_machine(self) -> None:
        problem = _make_medium_problem(n_orders=3, ops_per_order=2, n_machines=1)
        wc_id = problem.work_centers[0].id
        assignment = {op.id: wc_id for op in problem.operations}
        clusters = partition_machines(problem, assignment, max_ops_per_cluster=200)
        assert len(clusters) == 1
        assert wc_id in clusters[0]

    def test_respects_max_ops_cap(self) -> None:
        # Use enough machines so no single machine exceeds the cap
        problem = _make_medium_problem(n_orders=20, ops_per_order=5, n_machines=10)
        wcs = [wc.id for wc in problem.work_centers]
        assignment = {}
        for i, op in enumerate(problem.operations):
            assignment[op.id] = wcs[i % len(wcs)]

        clusters = partition_machines(problem, assignment, max_ops_per_cluster=30)
        for cluster in clusters:
            cluster_ops = sum(1 for v in assignment.values() if v in cluster)
            # A cluster may exceed the cap only if it contains a single machine
            # whose own ops exceed the cap (can't split a machine)
            if len(cluster) > 1:
                assert cluster_ops <= 30, f"Multi-machine cluster has {cluster_ops} ops, cap is 30"

    def test_all_machines_covered(self) -> None:
        problem = _make_medium_problem(n_orders=5, ops_per_order=3, n_machines=5)
        wcs = [wc.id for wc in problem.work_centers]
        assignment = {op.id: wcs[i % len(wcs)] for i, op in enumerate(problem.operations)}

        clusters = partition_machines(problem, assignment, max_ops_per_cluster=200)
        all_clustered = set()
        for c in clusters:
            all_clustered.update(c)

        assigned_machines = set(assignment.values())
        assert assigned_machines.issubset(all_clustered)

    def test_arc_affinity_groups_together(self) -> None:
        """Machines sharing ARC resources should be in the same cluster when possible."""
        problem = _make_medium_problem(
            n_orders=4, ops_per_order=2, n_machines=4, with_aux=True,
        )
        wcs = [wc.id for wc in problem.work_centers]
        assignment = {op.id: wcs[i % len(wcs)] for i, op in enumerate(problem.operations)}

        clusters = partition_machines(
            problem, assignment, max_ops_per_cluster=200,
        )
        # With a generous cap, ARC-linked machines should be co-clustered
        # (not split across many clusters)
        assert len(clusters) <= 3


# ---------------------------------------------------------------------------
# LBBD-HD Solver Tests
# ---------------------------------------------------------------------------


class TestLbbdHdSolver:
    def test_produces_feasible_result(self) -> None:
        problem = _make_medium_problem(n_orders=3, ops_per_order=3, n_machines=3)
        solver = LbbdHdSolver()
        result = solver.solve(
            problem, max_iterations=3, time_limit_s=60, use_warm_start=True,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.solver_name == "lbbd_hd"
        assert len(result.assignments) > 0

    def test_all_operations_assigned(self) -> None:
        problem = _make_medium_problem(n_orders=3, ops_per_order=3, n_machines=3)
        solver = LbbdHdSolver()
        result = solver.solve(
            problem, max_iterations=3, time_limit_s=60,
        )

        assigned_ops = {a.operation_id for a in result.assignments}
        expected_ops = {op.id for op in problem.operations}
        assert assigned_ops == expected_ops

    def test_passes_feasibility_checker(self) -> None:
        problem = _make_medium_problem(n_orders=3, ops_per_order=3, n_machines=3)
        solver = LbbdHdSolver()
        result = solver.solve(
            problem, max_iterations=3, time_limit_s=60,
        )

        checker = FeasibilityChecker()
        violations = checker.check(problem, result.assignments)
        assert violations == [], f"Violations found: {violations}"

    def test_respects_precedence(self) -> None:
        problem = _make_medium_problem(n_orders=3, ops_per_order=4, n_machines=3)
        solver = LbbdHdSolver()
        result = solver.solve(
            problem, max_iterations=3, time_limit_s=60,
        )

        assignment_map = {a.operation_id: a for a in result.assignments}
        for op in problem.operations:
            if op.predecessor_op_id and op.predecessor_op_id in assignment_map:
                pred = assignment_map[op.predecessor_op_id]
                cur = assignment_map[op.id]
                assert cur.start_time >= pred.end_time, (
                    f"Op {op.id} starts before predecessor ends"
                )

    def test_metadata_structure(self) -> None:
        problem = _make_medium_problem(n_orders=2, ops_per_order=2, n_machines=2)
        solver = LbbdHdSolver()
        result = solver.solve(
            problem, max_iterations=3, time_limit_s=60,
        )

        assert "lower_bound" in result.metadata
        assert "upper_bound" in result.metadata
        assert "iteration_log" in result.metadata
        assert "max_ops_per_cluster" in result.metadata
        assert "warm_start_used" in result.metadata
        assert "cut_pool" in result.metadata
        assert "size" in result.metadata["cut_pool"]

    def test_warm_start_improves_convergence(self) -> None:
        """With warm start, we should get at least one master warm-start iteration."""
        problem = _make_medium_problem(n_orders=5, ops_per_order=3, n_machines=3)
        solver = LbbdHdSolver()
        result = solver.solve(
            problem, max_iterations=5, time_limit_s=60, use_warm_start=True,
        )

        assert result.metadata.get("master_warm_start_iterations", 0) >= 1

    def test_makespan_is_positive(self) -> None:
        problem = _make_medium_problem(n_orders=3, ops_per_order=2, n_machines=2)
        solver = LbbdHdSolver()
        result = solver.solve(problem, max_iterations=3, time_limit_s=60)

        assert result.objective is not None
        assert result.objective.makespan_minutes > 0

    def test_with_aux_resources(self) -> None:
        """LBBD-HD should handle ARC constraints."""
        problem = _make_medium_problem(
            n_orders=4, ops_per_order=3, n_machines=3, with_aux=True,
        )
        solver = LbbdHdSolver()
        result = solver.solve(
            problem, max_iterations=3, time_limit_s=60,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(result.assignments) == len(problem.operations)

    def test_cut_pool_grows_with_iterations(self) -> None:
        problem = _make_medium_problem(n_orders=5, ops_per_order=3, n_machines=3)
        solver = LbbdHdSolver()
        result = solver.solve(
            problem, max_iterations=5, time_limit_s=60,
        )

        # After multiple iterations, cuts should have been generated
        cut_pool = result.metadata.get("cut_pool", {})
        if result.metadata.get("iterations", 0) > 1:
            assert cut_pool.get("size", 0) > 0

    def test_cluster_cap_respected(self) -> None:
        """Verify partitioning creates multiple clusters when ops exceed cap."""
        problem = _make_medium_problem(n_orders=8, ops_per_order=4, n_machines=8)
        solver = LbbdHdSolver()
        result = solver.solve(
            problem,
            max_iterations=3,
            time_limit_s=60,
            max_ops_per_cluster=10,
        )

        if result.metadata.get("iteration_log"):
            # With 32 ops and cap=10, we should see multiple clusters
            for entry in result.metadata["iteration_log"]:
                if "cluster_count" in entry:
                    assert entry["cluster_count"] >= 2, (
                        "Expected multiple clusters with low cap"
                    )


# ---------------------------------------------------------------------------
# Solver Integration: Registry + Router
# ---------------------------------------------------------------------------


class TestLbbdHdRegistryRouter:
    def test_hd_configs_in_registry(self) -> None:
        from synaps.solvers.registry import available_solver_configs

        configs = available_solver_configs()
        assert "LBBD-5-HD" in configs
        assert "LBBD-10-HD" in configs
        assert "LBBD-20-HD" in configs

    def test_create_hd_solver(self) -> None:
        from synaps.solvers.registry import create_solver

        solver, kwargs = create_solver("LBBD-10-HD")
        assert solver.name == "lbbd_hd"
        assert kwargs.get("max_iterations") == 10
        assert kwargs.get("num_workers") == 8

    def test_router_selects_hd_for_large_instance(self) -> None:
        from synaps.solvers.router import route_solver_config

        # 1000 op instance
        problem = _make_medium_problem(n_orders=200, ops_per_order=5, n_machines=20)
        decision = route_solver_config(problem)
        assert decision.solver_config in ("LBBD-10-HD", "LBBD-20-HD")

    def test_router_keeps_lbbd_for_medium(self) -> None:
        from synaps.solvers.router import route_solver_config

        problem = _make_medium_problem(n_orders=8, ops_per_order=4, n_machines=5)
        decision = route_solver_config(problem)
        # ~32 ops → should be CPSAT, not LBBD-HD
        assert "HD" not in decision.solver_config


# ---------------------------------------------------------------------------
# Problem Profile Size Bands
# ---------------------------------------------------------------------------


class TestProblemProfileSizeBands:
    def test_industrial_band(self) -> None:
        from synaps.problem_profile import build_problem_profile

        problem = _make_medium_problem(n_orders=150, ops_per_order=5, n_machines=20)
        profile = build_problem_profile(problem)
        assert profile.size_band == "industrial"

    def test_industrial_hd_band(self) -> None:
        from synaps.problem_profile import build_problem_profile

        problem = _make_medium_problem(n_orders=400, ops_per_order=8, n_machines=40)
        profile = build_problem_profile(problem)
        assert profile.size_band == "industrial-hd"

    def test_large_band_boundary(self) -> None:
        from synaps.problem_profile import build_problem_profile

        problem = _make_medium_problem(n_orders=25, ops_per_order=4, n_machines=5)
        profile = build_problem_profile(problem)
        # 100 ops → medium
        assert profile.size_band == "medium"


# ---------------------------------------------------------------------------
# Benchmark Presets
# ---------------------------------------------------------------------------


class TestBenchmarkPresets:
    def test_industrial_10k_preset_exists(self) -> None:
        from benchmark.generate_instances import preset_spec

        spec = preset_spec("industrial-10k")
        assert spec.n_jobs == 1500
        assert spec.n_machines == 100

    def test_industrial_50k_preset_exists(self) -> None:
        from benchmark.generate_instances import preset_spec

        spec = preset_spec("industrial-50k")
        assert spec.n_jobs == 6000
        assert spec.n_machines == 200

    def test_industrial_2k_preset_exists(self) -> None:
        from benchmark.generate_instances import preset_spec

        spec = preset_spec("industrial-2k")
        assert spec.n_jobs == 300
        assert spec.n_machines == 50

    def test_industrial_5k_preset_exists(self) -> None:
        from benchmark.generate_instances import preset_spec

        spec = preset_spec("industrial-5k")
        assert spec.n_jobs == 700
        assert spec.n_machines == 80
