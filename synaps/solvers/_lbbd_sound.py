"""Sound LBBD master relaxation (T-06): valid inequalities, never discounts.

KI-S3 retired every optimality cut that DISCOUNTED a subproblem value per
moved operation: ``L(S) - L(S \\ {j})`` can exceed ``p_j``, so those cuts could
lift the master above the optimum. This module adds rows of the opposite kind.
Each row below is satisfied by EVERY feasible schedule of the problem,
whatever its assignment. A master made of the assignment rows plus any set of
these rows is therefore a relaxation of the scheduling problem: its proven
dual bound is a valid makespan lower bound, no matter at which incumbent a row
was separated. Statements and proofs: ``docs/rfc/T06_SOUND_LBBD_RELAXATION.md``.

Notation (integer-minute reservation grain of every solver, P0-4):

* ``p_jk = duration_minutes_for(j, k)``, ``L_k = max_parallel``;
* head ``h_j``: the CEIL release / ``earliest_start`` offset raised by the
  predecessor chain at fastest durations — every schedule starts ``j`` at
  ``>= h_j``;
* tail ``t_j``: the longest successor chain at fastest durations — every
  schedule has ``C_max >= end_j + t_j``;
* ``s_k``: the setup matrix of machine ``k``; a missing cell is 0, as in every
  solver. ``y_jk`` is the assignment, ``z_kx >= y_jk`` marks state ``x`` as used
  on ``k``, ``C`` is the master makespan.

Row families (``C >= ...``):

* ``chain``: ``h_i + sum_{j on the path i..leaf} sum_k p_jk y_jk``;
* ``energy``: ``r + q - f_k + sum_{j: h_j>=r, t_j>=q} (p_jk / L_k + f_k) y_jk``,
  separated lazily, only for ANCHORED ``(r, q)``: some operation ``i`` (on any
  machine) has ``h_i >= r`` and ``t_i >= q``. Without the anchor an empty set
  would claim ``C >= r + q`` (measured: 31 > BKS 26 on Brandimarte ``mk02``);
  ``f_k`` is the transition floor of a single-lane machine;
* ``setup_in`` / ``setup_out`` (single-lane): ``sum_j p_jk y_jk +
  sum_x in_kx z_kx - max_x in_kx`` — every used state but the first is
  entered from another state at least once (``out``: left, all but the last);
* ``state_path`` (single-lane, separated lazily):
  ``sum_j p_jk y_jk + HP_k(X) - sum_{x in X} ins_kx (1 - z_kx)`` where
  ``HP_k`` is the shortest Hamiltonian path over ``X`` in the METRIC CLOSURE of
  ``s_k`` over all states routable to ``k``. On a metric matrix ``HP`` is
  monotone in the state set, and inserting ``x`` costs at most ``ins_kx``
  (append or prepend), so the row never over-claims (unlike KI-S3's raw BHK).

Multi-lane machines get capacity rows only (no setups): CP-SAT does not
model setups on them, and dropping setups keeps every row valid under any
lane-setup semantics. Calendars, auxiliary resources and ``latest_finish``
only remove schedules, so they never invalidate a row; operations with
execution modes are out of scope (LBBD rejects them up front).
"""

from __future__ import annotations

import bisect
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import highspy
import numpy as np

from synaps.solvers._lbbd_cuts import (
    _bhk_shortest_hamiltonian_path,
    _close_metrically,
    compute_machine_transition_floor,
)
from synaps.solvers._time_windows import operation_earliest_offset_minutes
from synaps.timegrain import duration_minutes_for

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from uuid import UUID

    from synaps.model import ScheduleProblem

#: Largest state set the lazy ``state_path`` separator solves exactly (BHK).
STATE_PATH_MAX_STATES = 12
#: Separation tolerance (minutes): a row must beat the incumbent by more.
VIOLATION_EPS = 1e-6

YKey = tuple["UUID", "UUID"]  # (operation, work center)
ZKey = tuple["UUID", "UUID"]  # (work center, state)


@dataclass(frozen=True)
class SoundRow:
    """One valid inequality ``C >= sum(y_coef * y) + sum(z_coef * z) + rhs``."""

    kind: str
    y_coef: tuple[tuple[YKey, float], ...]
    z_coef: tuple[tuple[ZKey, float], ...]
    rhs: float

    @property
    def key(self) -> tuple[str, frozenset[Any], frozenset[Any], float]:
        """Deduplication key (rhs to 1e-6 minute)."""
        return (self.kind, frozenset(self.y_coef), frozenset(self.z_coef), round(self.rhs, 6))

    def value(self, assignment: Mapping[UUID, UUID], state_of: Mapping[UUID, UUID]) -> float:
        """Right-hand side at an integer assignment (``z`` = state used on machine)."""
        used = {(wc_id, state_of[op_id]) for op_id, wc_id in assignment.items()}
        total = self.rhs
        total += sum(c for (op_id, wc_id), c in self.y_coef if assignment.get(op_id) == wc_id)
        total += sum(c for zkey, c in self.z_coef if zkey in used)
        return total


@dataclass
class _Machine:
    """Per-machine data: eligible operations, lanes, floor and setup geometry."""

    wc_id: UUID
    lanes: int
    floor: float
    ops: list[UUID]
    states: list[UUID] = field(default_factory=list)
    entry: dict[UUID, float] = field(default_factory=dict)
    exit: dict[UUID, float] = field(default_factory=dict)
    closure: list[list[float]] = field(default_factory=list)
    insertion: dict[UUID, float] = field(default_factory=dict)


class SoundRelaxation:
    """Static data and separators of the sound master relaxation for one problem."""

    def __init__(self, problem: ScheduleProblem) -> None:
        self.problem = problem
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        all_wc_ids = [wc.id for wc in problem.work_centers]
        self.eligible: dict[UUID, list[UUID]] = {
            op.id: list(op.eligible_wc_ids or all_wc_ids) for op in problem.operations
        }
        self.duration: dict[YKey, float] = {
            (op.id, wc_id): float(duration_minutes_for(op, wc_by_id[wc_id]))
            for op in problem.operations
            for wc_id in self.eligible[op.id]
        }
        self.state_of: dict[UUID, UUID] = {op.id: op.state_id for op in problem.operations}
        self.setup: dict[tuple[UUID, UUID, UUID], float] = {
            (e.work_center_id, e.from_state_id, e.to_state_id): float(e.setup_minutes)
            for e in problem.setup_matrix
        }
        self._init_heads_and_tails()
        self.machines: list[_Machine] = []
        for wc in problem.work_centers:
            ops = [op.id for op in problem.operations if wc.id in self.eligible[op.id]]
            single = wc.max_parallel <= 1
            floor = (
                compute_machine_transition_floor(problem, self.eligible, wc.id, self.setup)
                if single
                else 0.0
            )
            machine = _Machine(wc.id, max(1, wc.max_parallel), floor, ops)
            if single:
                self._init_setup_geometry(machine)
            self.machines.append(machine)

    # -- static data ---------------------------------------------------------

    def _init_heads_and_tails(self) -> None:
        problem = self.problem
        ids = {op.id for op in problem.operations}
        orders = {order.id: order for order in problem.orders}
        self.fastest = {
            op.id: min(self.duration[(op.id, wc_id)] for wc_id in self.eligible[op.id])
            for op in problem.operations
        }
        self.release = {
            op.id: operation_earliest_offset_minutes(
                op, orders.get(op.order_id), problem.planning_horizon_start
            )
            for op in problem.operations
        }
        self.predecessor: dict[UUID, UUID] = {
            op.id: op.predecessor_op_id
            for op in problem.operations
            if op.predecessor_op_id is not None and op.predecessor_op_id in ids
        }
        self.successors: dict[UUID, list[UUID]] = defaultdict(list)
        for child, parent in self.predecessor.items():
            self.successors[parent].append(child)
        order = self._topological_order()
        # A precedence cycle leaves its operations out of ``order``: they keep
        # head = release and tail = 0 (still valid) and get no chain rows.
        self.acyclic = set(order)
        self.head = dict(self.release)
        for op_id in order:
            pred = self.predecessor.get(op_id)
            if pred is not None:
                self.head[op_id] = max(self.head[op_id], self.head[pred] + self.fastest[pred])
        self.tail = dict.fromkeys(self.release, 0.0)
        for op_id in reversed(order):
            self.tail[op_id] = max(
                (self.fastest[s] + self.tail[s] for s in self.successors.get(op_id, [])),
                default=0.0,
            )
        # Anchor test for energy thresholds: max tail among heads >= r.
        pairs = sorted((self.head[i], self.tail[i]) for i in self.head)
        self._anchor_heads = [h for h, _ in pairs]
        self._anchor_tail_suffix_max = [0.0] * len(pairs)
        running = float("-inf")
        for index in range(len(pairs) - 1, -1, -1):
            running = max(running, pairs[index][1])
            self._anchor_tail_suffix_max[index] = running

    def _topological_order(self) -> list[UUID]:
        indegree = {op.id: int(op.id in self.predecessor) for op in self.problem.operations}
        frontier = [op.id for op in self.problem.operations if indegree[op.id] == 0]
        order: list[UUID] = []
        while frontier:
            op_id = frontier.pop()
            order.append(op_id)
            for child in self.successors.get(op_id, []):
                indegree[child] -= 1
                if indegree[child] == 0:
                    frontier.append(child)
        return order

    def _init_setup_geometry(self, machine: _Machine) -> None:
        states = sorted({self.state_of[op_id] for op_id in machine.ops}, key=str)
        wc_id = machine.wc_id

        def cost(a: UUID, b: UUID) -> float:
            return self.setup.get((wc_id, a, b), 0.0)

        if len(states) < 2 or all(cost(a, b) <= 0 for a in states for b in states if a != b):
            return  # no positive cross-state setup: no z columns, no setup rows
        machine.states = states

        others = {x: [v for v in states if v != x] for x in states}
        machine.entry = {x: min(cost(v, x) for v in others[x]) for x in states}
        machine.exit = {x: min(cost(x, v) for v in others[x]) for x in states}
        n = len(states)
        closure = [
            [0.0 if i == j else cost(states[i], states[j]) for j in range(n)] for i in range(n)
        ]
        _close_metrically(closure)
        machine.closure = closure
        machine.insertion = {
            x: min(
                max(closure[u][i] for u in range(n) if u != i),
                max(closure[i][u] for u in range(n) if u != i),
            )
            for i, x in enumerate(states)
        }

    def anchored(self, r: float, q: float) -> bool:
        """True when some operation has ``h_i >= r`` and ``t_i >= q``."""
        index = bisect.bisect_left(self._anchor_heads, r - 1e-9)
        return index < len(self._anchor_heads) and self._anchor_tail_suffix_max[index] >= q - 1e-9

    # -- rows ----------------------------------------------------------------

    def z_keys(self) -> list[ZKey]:
        """State-usage columns ``z_kx`` (single-lane machines with >= 2 states)."""
        return [(m.wc_id, x) for m in self.machines if m.states for x in m.states]

    def z_links(self) -> list[tuple[ZKey, YKey]]:
        """``z_kx >= y_jk`` for every operation ``j`` of state ``x`` routable to ``k``."""
        return [
            ((m.wc_id, self.state_of[op_id]), (op_id, m.wc_id))
            for m in self.machines
            if m.states
            for op_id in m.ops
        ]

    def static_rows(self, *, include_capacity: bool = False) -> list[SoundRow]:
        """Rows added to every master: chains and state entry / exit setups."""
        rows = self._chain_rows()
        for machine in self.machines:
            if include_capacity:
                rows.append(self._capacity_row(machine))
            for kind, minima in (("setup_in", machine.entry), ("setup_out", machine.exit)):
                if minima and max(minima.values()) > 0:
                    rows.append(
                        SoundRow(
                            kind,
                            self._load_terms(machine),
                            tuple(
                                ((machine.wc_id, x), c) for x, c in sorted(minima.items(), key=str)
                            ),
                            -max(minima.values()),
                        )
                    )
        return rows

    def _load_terms(self, machine: _Machine) -> tuple[tuple[YKey, float], ...]:
        return tuple(
            ((op_id, machine.wc_id), self.duration[(op_id, machine.wc_id)]) for op_id in machine.ops
        )

    def _capacity_row(self, machine: _Machine) -> SoundRow:
        """``C >= sum (p/L + f) y - f`` — the legacy master capacity row."""
        coef = tuple(
            (
                (op_id, machine.wc_id),
                self.duration[(op_id, machine.wc_id)] / machine.lanes + machine.floor,
            )
            for op_id in machine.ops
        )
        return SoundRow("capacity", coef, (), -machine.floor)

    def _chain_rows(self) -> list[SoundRow]:
        rows: list[SoundRow] = []
        leaves = [
            op.id
            for op in self.problem.operations
            if op.id in self.acyclic and not self.successors.get(op.id)
        ]
        for leaf in leaves:
            path = [leaf]
            while path[-1] in self.predecessor:
                path.append(self.predecessor[path[-1]])
            path.reverse()
            for index, op_id in enumerate(path):
                parent = self.predecessor.get(op_id)
                if (
                    parent is not None
                    and self.release[op_id] <= self.head[parent] + self.fastest[parent]
                ):
                    continue  # the row anchored at the parent dominates
                coef = tuple(
                    ((j, wc_id), self.duration[(j, wc_id)])
                    for j in path[index:]
                    for wc_id in self.eligible[j]
                )
                rows.append(SoundRow("chain", coef, (), self.head[op_id]))
        return rows

    def separate(self, assignment: Mapping[UUID, UUID], cmax: float) -> list[SoundRow]:
        """Lazy rows violated at an integer incumbent (``energy``, ``state_path``)."""
        on_machine: dict[UUID, list[UUID]] = defaultdict(list)
        for op_id, wc_id in assignment.items():
            on_machine[wc_id].append(op_id)
        rows: list[SoundRow] = []
        for machine in self.machines:
            assigned = on_machine.get(machine.wc_id, [])
            if not assigned:
                continue
            energy = self._most_violated_energy_row(machine, assigned, cmax)
            if energy is not None:
                rows.append(energy)
            path = self._state_path_row(machine, assigned, cmax)
            if path is not None:
                rows.append(path)
        return rows

    def _most_violated_energy_row(
        self, machine: _Machine, assigned: list[UUID], cmax: float
    ) -> SoundRow | None:
        """O(n^2) sweep: for each head threshold, accumulate by decreasing tail.

        A value read before the last operation of a tail group omits part of
        the group, so it is below the true window value; the maximum over all
        reads is still exact (attained at the end of a group).
        """
        wc_id, lanes, floor = machine.wc_id, machine.lanes, machine.floor
        by_tail = sorted(assigned, key=lambda j: (-self.tail[j], str(j)))
        best_value, best = cmax + VIOLATION_EPS, None
        for r in sorted({self.head[j] for j in assigned}):
            load = -floor
            for j in by_tail:
                if self.head[j] < r:
                    continue
                load += self.duration[(j, wc_id)] / lanes + floor
                q = self.tail[j]
                if r + q + load > best_value and self.anchored(r, q):
                    best_value, best = r + q + load, (r, q)
        return None if best is None else self.energy_row(machine, *best)

    def energy_row(self, machine: _Machine, r: float, q: float) -> SoundRow:
        """``C >= r + q - f + sum_{h_j >= r, t_j >= q} (p_jk / L + f) y_jk`` (anchored ``r, q``)."""
        wc_id, lanes, floor = machine.wc_id, machine.lanes, machine.floor
        coef = tuple(
            ((j, wc_id), self.duration[(j, wc_id)] / lanes + floor)
            for j in machine.ops
            if self.head[j] >= r and self.tail[j] >= q
        )
        return SoundRow("energy", coef, (), r + q - floor)

    def _state_path_row(
        self, machine: _Machine, assigned: list[UUID], cmax: float
    ) -> SoundRow | None:
        if not machine.states:
            return None
        used = sorted({self.state_of[j] for j in assigned}, key=str)
        if not 2 <= len(used) <= STATE_PATH_MAX_STATES:
            return None
        row = self.state_path_row(machine, used)
        load = sum(self.duration[(j, machine.wc_id)] for j in assigned)
        hp = row.rhs + sum(c for _, c in row.z_coef)
        if hp <= 0 or load + hp <= cmax + VIOLATION_EPS:
            return None
        return row

    def state_path_row(self, machine: _Machine, states: list[UUID]) -> SoundRow:
        """``C >= sum_j p_jk y_jk + HP_k(X) - sum_{x in X} ins_kx (1 - z_kx)``."""
        index = {x: i for i, x in enumerate(machine.states)}
        nodes = [index[x] for x in states]
        hp = _bhk_shortest_hamiltonian_path([[machine.closure[a][b] for b in nodes] for a in nodes])
        z_coef = tuple(((machine.wc_id, x), machine.insertion[x]) for x in states)
        rhs = hp - sum(machine.insertion[x] for x in states)
        return SoundRow("state_path", self._load_terms(machine), z_coef, rhs)


@dataclass(frozen=True)
class SoundMasterBound:
    """Result of :func:`compute_sound_master_lower_bound`."""

    value: float
    rows_by_kind: dict[str, int]
    rounds: int
    converged: bool


class SoundMaster:
    """Row pool and HiGHS glue for the sound rows of one solve."""

    def __init__(self, relaxation: SoundRelaxation, *, mip_rel_gap: float | None = None) -> None:
        self.relaxation = relaxation
        # HiGHS relative MIP gap for every master this pool is attached to.
        # Stopping early keeps ``mip_dual_bound`` valid and leaves time for
        # more separation rounds (``None`` = HiGHS default, 1e-4).
        self.mip_rel_gap = mip_rel_gap
        self.pool: list[SoundRow] = []
        self._seen: set[tuple[str, frozenset[Any], frozenset[Any], float]] = set()
        self.add_to_pool(relaxation.static_rows())
        self.static_count = len(self.pool)
        self.rounds = 0

    def add_to_pool(self, rows: Iterable[SoundRow]) -> list[SoundRow]:
        fresh: list[SoundRow] = []
        for row in rows:
            if row.key not in self._seen:
                self._seen.add(row.key)
                self.pool.append(row)
                fresh.append(row)
        return fresh

    def rows_by_kind(self) -> dict[str, int]:
        return dict(sorted(Counter(row.kind for row in self.pool).items()))

    def attach(self, h: Any, var_index: Mapping[YKey, int], cmax_idx: int) -> dict[ZKey, int]:
        """Add ``z`` columns, their links and every pooled row to a HiGHS master."""
        if self.mip_rel_gap is not None:
            h.setOptionValue("mip_rel_gap", float(self.mip_rel_gap))
        z_keys = self.relaxation.z_keys()
        first = int(h.getNumCol())
        if z_keys:
            n = len(z_keys)
            h.addVars(n, np.zeros(n), np.ones(n))
        z_index = {key: first + offset for offset, key in enumerate(z_keys)}
        for zkey, ykey in self.relaxation.z_links():
            if ykey in var_index:
                _add_row(h, 0.0, highspy.kHighsInf, [z_index[zkey], var_index[ykey]], [1.0, -1.0])
        for row in self.pool:
            _add_sound_row(h, row, var_index, z_index, cmax_idx)
        return z_index

    def solve(
        self,
        h: Any,
        var_index: Mapping[YKey, int],
        z_index: Mapping[ZKey, int],
        cmax_idx: int,
        deadline: float,
        max_rounds: int,
    ) -> tuple[bool, float]:
        """Run, then separate lazy rows at each incumbent.

        Returns ``(converged, best_dual)``. ``converged``: no lazy row is
        violated at the last incumbent. ``best_dual``: the largest proven dual
        bound over all runs — every run's model holds only valid rows, so each
        run's bound is valid, and a later run cut short by the clock may prove
        less than an earlier one.
        """
        h.run()
        best = _dual_bound(h)
        for _ in range(max_rounds):
            if h.getInfoValue("primal_solution_status")[1] != 2:
                return False, best
            remaining = deadline - time.monotonic()
            if remaining <= 0.05:
                return False, best
            values = h.getSolution().col_value
            assignment = _incumbent_assignment(self.relaxation.eligible, var_index, values)
            fresh = self.add_to_pool(self.relaxation.separate(assignment, float(values[cmax_idx])))
            if not fresh:
                return True, best
            for row in fresh:
                _add_sound_row(h, row, var_index, z_index, cmax_idx)
            self.rounds += 1
            h.setOptionValue("time_limit", max(0.05, remaining))
            h.run()
            best = max(best, _dual_bound(h))
        return False, best


def _dual_bound(h: Any) -> float:
    """HiGHS' proven MIP dual bound, or -inf when it published none."""
    value = float(h.getInfoValue("mip_dual_bound")[1])
    return value if np.isfinite(value) else float("-inf")


def _add_row(h: Any, lower: float, upper: float, indices: list[int], coefs: list[float]) -> None:
    h.addRow(lower, upper, len(indices), np.array(indices, dtype=np.int32), np.array(coefs))


def _add_sound_row(
    h: Any,
    row: SoundRow,
    var_index: Mapping[YKey, int],
    z_index: Mapping[ZKey, int],
    cmax_idx: int,
) -> None:
    """``sum(coef * var) - C <= -rhs``; terms of absent columns are dropped.

    A missing ``y`` column means the operation cannot run there (``y = 0``); a
    missing ``z`` column cannot occur because rows and columns share one
    :class:`SoundRelaxation`.
    """
    indices = [var_index[k] for k, _ in row.y_coef if k in var_index]
    coefs = [c for k, c in row.y_coef if k in var_index]
    indices += [z_index[k] for k, _ in row.z_coef]
    coefs += [c for _, c in row.z_coef]
    _add_row(h, -highspy.kHighsInf, -row.rhs, [*indices, cmax_idx], [*coefs, -1.0])


def _incumbent_assignment(
    eligible: Mapping[UUID, list[UUID]], var_index: Mapping[YKey, int], values: Any
) -> dict[UUID, UUID]:
    """Per operation, the machine whose ``y`` is largest (the LBBD extraction rule)."""
    assignment: dict[UUID, UUID] = {}
    for op_id, wc_ids in eligible.items():
        best_val, best_wc = -1.0, None
        for wc_id in wc_ids:
            key = (op_id, wc_id)
            if key in var_index and values[var_index[key]] > best_val:
                best_val, best_wc = values[var_index[key]], wc_id
        if best_wc is not None:
            assignment[op_id] = best_wc
    return assignment


def compute_sound_master_lower_bound(
    problem: ScheduleProblem,
    *,
    time_limit_s: float = 10.0,
    max_rounds: int = 50,
    master: SoundMaster | None = None,
) -> SoundMasterBound:
    """Makespan lower bound of the sound master relaxation (T-06, Rule 6).

    Builds ``min C`` over assignment rows, the capacity rows and the static
    sound rows, then separates lazy rows until none is violated, the round
    budget is spent or ``time_limit_s`` expires. The value is HiGHS'
    ``mip_dual_bound`` (the best over the separation runs) — a proof even when
    the MIP stops on its time limit — floored at 0. Passing ``master`` reuses
    its row pool (LBBD's final bound: rows separated during the run, never its
    no-goods).
    """
    deadline = time.monotonic() + max(0.0, float(time_limit_s))
    master = master if master is not None else SoundMaster(SoundRelaxation(problem))
    relaxation = master.relaxation
    if not problem.operations:
        return SoundMasterBound(0.0, master.rows_by_kind(), 0, True)
    h = highspy.Highs()
    h.silent()
    h.setOptionValue("time_limit", max(0.05, float(time_limit_s)))
    var_index: dict[YKey, int] = {key: i for i, key in enumerate(relaxation.duration)}
    n_y = len(var_index)
    cmax_idx = n_y
    h.addVars(n_y + 1, np.zeros(n_y + 1), np.array([1.0] * n_y + [highspy.kHighsInf]))
    costs = np.zeros(n_y + 1)
    costs[cmax_idx] = 1.0
    h.changeColsCost(n_y + 1, np.arange(n_y + 1, dtype=np.int32), costs)
    h.changeColsIntegrality(
        n_y, np.arange(n_y, dtype=np.int32), np.array([highspy.HighsVarType.kInteger] * n_y)
    )
    for op_id, wc_ids in relaxation.eligible.items():
        indices = [var_index[(op_id, wc_id)] for wc_id in wc_ids]
        _add_row(h, 1.0, 1.0, indices, [1.0] * len(indices))
    for machine in relaxation.machines:
        if machine.ops:
            _add_sound_row(h, relaxation._capacity_row(machine), var_index, {}, cmax_idx)
    z_index = master.attach(h, var_index, cmax_idx)
    rounds_before = master.rounds
    converged, best_dual = master.solve(h, var_index, z_index, cmax_idx, deadline, max_rounds)
    return SoundMasterBound(
        value=max(0.0, best_dual),
        rows_by_kind=master.rows_by_kind(),
        rounds=master.rounds - rounds_before,
        converged=converged,
    )


__all__ = [
    "STATE_PATH_MAX_STATES",
    "SoundMaster",
    "SoundMasterBound",
    "SoundRelaxation",
    "SoundRow",
    "compute_sound_master_lower_bound",
]
