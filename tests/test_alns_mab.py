"""T-34 / Wave 5–6: UCB1 pair bandit smoke tests."""

from __future__ import annotations

from synaps.solvers._alns_mab import PairBandit, pair_reward


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
