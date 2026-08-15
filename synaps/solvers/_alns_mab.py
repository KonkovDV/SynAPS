"""UCB1 selection over ALNS (destroy, repair) pairs (T-34 / Wave 5).

Opt-in via ``mab_pair_selection=True`` on the ALNS solver. Default remains the
legacy independent weight-proportional destroy/repair draws.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class PairBandit:
    """UCB1 over a fixed list of pair indices."""

    n_pairs: int
    pulls: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    total_pulls: int = 0

    def __post_init__(self) -> None:
        if self.n_pairs <= 0:
            raise ValueError("n_pairs must be positive")
        if not self.pulls:
            self.pulls = [0] * self.n_pairs
        if not self.values:
            self.values = [0.0] * self.n_pairs

    def select(self) -> int:
        """Return the pair index with the highest UCB1 score."""
        for idx, pulls in enumerate(self.pulls):
            if pulls == 0:
                return idx
        log_n = math.log(max(self.total_pulls, 1))
        best_idx = 0
        best_score = float("-inf")
        for idx, (pulls, value) in enumerate(zip(self.pulls, self.values, strict=True)):
            score = value + math.sqrt(2.0 * log_n / pulls)
            if score > best_score:
                best_score = score
                best_idx = idx
        return best_idx

    def update(self, pair_idx: int, reward: float) -> None:
        """Incremental mean update for ``pair_idx`` with reward in ``[-1, 1]``."""
        self.total_pulls += 1
        self.pulls[pair_idx] += 1
        n = self.pulls[pair_idx]
        self.values[pair_idx] += (reward - self.values[pair_idx]) / n


def pair_reward(*, cost_before: float, cost_after: float, accepted: bool) -> float:
    """Normalized improvement reward used by the design note."""
    if not accepted:
        return -0.05
    denom = max(abs(cost_before), 1.0)
    return max(0.0, (cost_before - cost_after) / denom)


def charge_pair_reject(bandit: PairBandit | None, pair_idx: int) -> None:
    """Credit a rejected / aborted pair so UCB1 cannot livelock on arm 0."""
    if bandit is None or pair_idx < 0:
        return
    bandit.update(pair_idx, pair_reward(cost_before=1.0, cost_after=1.0, accepted=False))


def pair_pulls(bandit: PairBandit | None, labels: list[str]) -> dict[str, int]:
    """Per-arm pull counts for ALNS metadata. Empty when MAB is off."""

    if bandit is None:
        return {}
    return {label: int(bandit.pulls[idx]) for idx, label in enumerate(labels)}


__all__ = ["PairBandit", "charge_pair_reject", "pair_pulls", "pair_reward"]
