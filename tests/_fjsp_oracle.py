"""Exhaustive FJSP-SDST oracle for tiny instances (T-06 validity tests).

The oracle enumerates every assignment and every machine sequence, so its
optimum is a ground truth that does not depend on any solver under test. Its
semantics mirror CP-SAT (``synaps/solvers/cpsat_solver.py``) on the subset the
sound LBBD rows reason about:

* ``p_jk = duration_minutes_for(j, k)``; ``start_j >= ceil(release /
  earliest_start offset)`` (``operation_earliest_offset_minutes``);
* chain precedence ``start_succ >= end_pred``;
* a lane is a disjunctive sequence: ``start_j >= end_i + s_k(state_i, state_j)``
  for consecutive ``i -> j``; the first operation pays no setup (CP-SAT depot
  arcs carry none);
* a work center with ``max_parallel = L`` is ``L`` identical lanes with setups
  inside each lane — CP-SAT's ``_virtualize_parallel_work_centers`` (without
  setups this is plain cumulative capacity ``L``: an interval family of depth
  ``<= L`` is ``L``-colourable);
* every operation must end by the planning horizon.

For fixed lane sequences the earliest-start schedule is the least solution of
the difference constraints (a longest path); a regular objective is optimised
by such semi-active schedules, so the optimum of an assignment is the minimum
over sequences. Calendars, auxiliary resources, ``latest_finish``, modes and
``precedence_edges`` are rejected — they only remove schedules and are outside
the oracle's scope.
"""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING

from synaps.solvers._time_windows import operation_earliest_offset_minutes
from synaps.timegrain import duration_minutes_for

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from synaps.model import ScheduleProblem

Assignment = tuple[tuple["UUID", "UUID"], ...]


def _check_scope(problem: ScheduleProblem) -> None:
    unsupported = (
        any(wc.calendar for wc in problem.work_centers)
        or problem.auxiliary_resources
        or problem.aux_requirements
        or problem.precedence_edges
        or any(op.modes or op.latest_finish is not None for op in problem.operations)
    )
    if unsupported:
        raise ValueError("oracle scope: no calendars, aux, latest_finish, modes or edges")


def _lane_layouts(ops: list[UUID], lanes: int) -> Iterator[list[tuple[UUID, ...]]]:
    """Every split of ``ops`` into ``lanes`` ordered sequences (lanes unlabelled)."""
    seen: set[tuple[tuple[UUID, ...], ...]] = set()
    for labels in itertools.product(range(lanes), repeat=len(ops)):
        groups = [
            [op for op, lane in zip(ops, labels, strict=True) if lane == k] for k in range(lanes)
        ]
        for orders in itertools.product(*(itertools.permutations(g) for g in groups)):
            canonical = tuple(sorted(orders, key=lambda seq: tuple(map(str, seq))))
            if canonical not in seen:
                seen.add(canonical)
                yield list(canonical)


class Oracle:
    """Optimal makespan of every assignment of a tiny problem."""

    def __init__(self, problem: ScheduleProblem) -> None:
        _check_scope(problem)
        self.problem = problem
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        all_ids = [wc.id for wc in problem.work_centers]
        self.ops = [op.id for op in problem.operations]
        self.eligible = {op.id: list(op.eligible_wc_ids or all_ids) for op in problem.operations}
        self.lanes = {wc.id: max(1, wc.max_parallel) for wc in problem.work_centers}
        self.duration = {
            (op.id, k): duration_minutes_for(op, wc_by_id[k])
            for op in problem.operations
            for k in self.eligible[op.id]
        }
        orders = {order.id: order for order in problem.orders}
        self.release = {
            op.id: operation_earliest_offset_minutes(
                op, orders.get(op.order_id), problem.planning_horizon_start
            )
            for op in problem.operations
        }
        self.predecessor = {
            op.id: op.predecessor_op_id
            for op in problem.operations
            if op.predecessor_op_id is not None
        }
        self.state = {op.id: op.state_id for op in problem.operations}
        self.setup = {
            (e.work_center_id, e.from_state_id, e.to_state_id): e.setup_minutes
            for e in problem.setup_matrix
        }
        self.horizon = (
            problem.planning_horizon_end - problem.planning_horizon_start
        ).total_seconds() / 60.0

    def assignments(self) -> Iterator[dict[UUID, UUID]]:
        for combo in itertools.product(*(self.eligible[op_id] for op_id in self.ops)):
            yield dict(zip(self.ops, combo, strict=True))

    def optimum_for(self, assignment: dict[UUID, UUID]) -> float:
        """Optimal makespan for a fixed assignment (``inf`` when infeasible)."""
        by_machine: dict[UUID, list[UUID]] = {}
        for op_id in self.ops:
            by_machine.setdefault(assignment[op_id], []).append(op_id)
        machines = sorted(by_machine, key=str)
        layouts = [list(_lane_layouts(by_machine[k], self.lanes[k])) for k in machines]
        best = math.inf
        for choice in itertools.product(*layouts):
            sequences = [
                (k, lane) for k, lanes in zip(machines, choice, strict=True) for lane in lanes
            ]
            best = min(best, self._makespan(assignment, sequences))
        return best

    def optimum(self) -> float:
        return min((self.optimum_for(a) for a in self.assignments()), default=0.0)

    def _makespan(
        self, assignment: dict[UUID, UUID], sequences: list[tuple[UUID, tuple[UUID, ...]]]
    ) -> float:
        """Earliest-start makespan of fixed lane sequences (``inf`` on a cycle)."""
        incoming: dict[UUID, list[tuple[UUID, float]]] = {op_id: [] for op_id in self.ops}
        for op_id, parent in self.predecessor.items():
            incoming[op_id].append((parent, float(self.duration[(parent, assignment[parent])])))
        for k, lane in sequences:
            for prev, nxt in itertools.pairwise(lane):
                gap = self.duration[(prev, k)] + self.setup.get(
                    (k, self.state[prev], self.state[nxt]), 0
                )
                incoming[nxt].append((prev, float(gap)))
        start: dict[UUID, float] = {}
        pending = set(self.ops)
        while pending:
            ready = [op_id for op_id in pending if all(src in start for src, _ in incoming[op_id])]
            if not ready:
                return math.inf  # the sequences contradict the precedence chain
            for op_id in ready:
                start[op_id] = max(
                    [self.release[op_id], *(start[src] + gap for src, gap in incoming[op_id])]
                )
                pending.discard(op_id)
        makespan = max(
            start[op_id] + self.duration[(op_id, assignment[op_id])] for op_id in self.ops
        )
        return makespan if makespan <= self.horizon + 1e-9 else math.inf
