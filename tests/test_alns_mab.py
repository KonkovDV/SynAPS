"""T-34 / Wave 5–6 / K2: UCB1 pair bandit smoke + seeded determinism."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import Operation, Order, ScheduleProblem, SetupEntry, State, WorkCenter
from synaps.solvers._alns_mab import PairBandit, pair_pulls, pair_reward
from synaps.solvers.registry import get_solver_registration

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def test_pair_bandit_explores_unpulled_first() -> None:
    bandit = PairBandit(n_pairs=3)
    assert bandit.select() == 0
    bandit.update(0, 0.1)
    assert bandit.select() == 1
    bandit.update(1, 0.2)
    assert bandit.select() == 2


def test_pair_reward_accepted_improvement() -> None:
    assert pair_reward(cost_before=100.0, cost_after=80.0, accepted=True) == 0.2
    assert pair_reward(cost_before=100.0, cost_after=120.0, accepted=True) == 0.0
    assert pair_reward(cost_before=100.0, cost_after=80.0, accepted=False) == -0.05


def test_charge_pair_reject_prevents_livelock() -> None:
    from synaps.solvers._alns_mab import PairBandit, charge_pair_reject

    bandit = PairBandit(n_pairs=3)
    assert bandit.select() == 0
    charge_pair_reject(bandit, 0)
    assert bandit.pulls[0] == 1
    assert bandit.select() == 1


def test_pair_bandit_select_is_rng_free() -> None:
    """UCB1 has no hidden RNG. Same pulls/values ⇒ same arm (Auer et al. 2002)."""

    first = PairBandit(n_pairs=4)
    second = PairBandit(n_pairs=4)
    for idx, reward in ((0, 0.2), (1, 0.0), (2, 0.4), (3, -0.05), (2, 0.1)):
        first.update(idx, reward)
        second.update(idx, reward)
    assert first.select() == second.select()
    assert first.pulls == second.pulls
    assert first.values == second.values


def test_pair_pulls_empty_when_mab_off() -> None:
    assert pair_pulls(None, ["random|greedy"]) == {}


def _tiny_sdst_problem() -> ScheduleProblem:
    s1, s2 = State(code="a"), State(code="b")
    machines = [
        WorkCenter(code="M1", capability_group="G"),
        WorkCenter(code="M2", capability_group="G"),
    ]
    orders = [Order(external_ref=f"O{i}", due_date=_HE, priority=i) for i in range(4)]
    ops: list[Operation] = []
    for order in orders:
        ops.append(
            Operation(
                order_id=order.id,
                seq_in_order=1,
                state_id=s1.id,
                base_duration_min=5,
                eligible_wc_ids=[wc.id for wc in machines],
            )
        )
        ops.append(
            Operation(
                order_id=order.id,
                seq_in_order=2,
                state_id=s2.id,
                base_duration_min=5,
                eligible_wc_ids=[wc.id for wc in machines],
                predecessor_op_id=ops[-1].id,
            )
        )
    return ScheduleProblem(
        states=[s1, s2],
        orders=orders,
        operations=ops,
        work_centers=machines,
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=2,
            )
            for wc in machines
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )


def test_mab_pair_selection_defaults_off_and_registry_stays_roulette() -> None:
    from synaps.solvers.alns_solver import AlnsSolver

    result = AlnsSolver().solve(
        _tiny_sdst_problem(),
        time_limit_s=8,
        max_iterations=8,
        use_cpsat_repair=False,
        random_seed=7,
    )
    assert result.metadata.get("mab_pair_selection") is False
    assert result.metadata.get("mab_pair_count", 0) == 0
    assert result.metadata.get("mab_pair_pulls") == {}
    for name in ("ALNS-300", "ALNS-500", "ALNS-1000"):
        kwargs = get_solver_registration(name).solve_kwargs
        assert kwargs.get("mab_pair_selection", False) is False


def test_mab_alns_seeded_determinism() -> None:
    """K2: same seed + greedy repair + MAB ⇒ same cost and pull vector.

    CP-SAT repair is off: default ``use_cpsat_repair=True`` is not this claim.
    Wall-cut runs are K3 (``wall_clock_path_dependent``), not bitwise MAB.
    """

    from synaps.solvers.alns_solver import AlnsSolver

    problem = _tiny_sdst_problem()
    kwargs = {
        "time_limit_s": 20,
        "max_iterations": 12,
        "mab_pair_selection": True,
        "use_cpsat_repair": False,
        "random_seed": 123,
    }
    first = AlnsSolver().solve(problem, **kwargs)
    second = AlnsSolver().solve(problem, **kwargs)
    assert first.metadata.get("mab_pair_selection") is True
    assert first.metadata.get("mab_repair_modes") == ["greedy"]
    assert first.metadata.get("mab_pair_count", 0) >= 1
    pulls = first.metadata.get("mab_pair_pulls")
    assert isinstance(pulls, dict) and pulls
    assert second.metadata.get("mab_pair_pulls") == pulls
    assert first.objective.makespan_minutes == second.objective.makespan_minutes
    assert first.metadata.get("iterations_completed") == second.metadata.get(
        "iterations_completed"
    )
    assert first.metadata.get("search_stop_reason") == "max_iterations"
