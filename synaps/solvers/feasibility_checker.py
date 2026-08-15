"""Feasibility Checker — validates constraint satisfaction without solving."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from synaps.timegrain import duration_minutes_for, physical_processing_minutes_for


class _LaneSearchBudgetExceeded(Exception):
    """Internal control flow: the exact lane search hit its state budget (F7)."""


def _exact_lane_assignment(
    starts: list[Any],
    ends: list[Any],
    gap_minutes: Any,
    max_parallel: int,
) -> list[int] | None:
    """Memoized backtracking lane assignment (F7 engine).

    ``starts``/``ends`` are per-op datetimes in processing (start, end) order;
    ``gap_minutes(from_idx, to_idx)`` returns the setup minutes required when
    op ``to_idx`` directly follows op ``from_idx`` on a lane (``math.inf`` for
    a forbidden transition). Returns the lane index per op, or None when no
    assignment into at most ``max_parallel`` setup-aware lanes exists — a
    PROVEN infeasibility: processing in start order and branching over every
    admissible lane explores all assignments consistent with the time order.

    Lane interchangeability is quotiented out by memoizing failure states on
    the canonically sorted tail vector. ``_LaneSearchBudgetExceeded`` signals
    the caller to fall back to the greedy heuristic.
    """
    n = len(starts)
    visited: set[tuple[int, tuple[int, ...]]] = set()
    chosen: list[tuple[int, int]] = []  # (lane_idx, op_idx) along the path

    def search(i: int, tails: tuple[int, ...]) -> bool:
        if i == n:
            return True
        key = (i, tuple(sorted(tails)))
        if key in visited:
            return False
        if len(visited) >= _LANE_EXACT_STATE_BUDGET:
            raise _LaneSearchBudgetExceeded
        # Candidate lanes: distinct non-empty tails that admit the gap,
        # tightest (latest-available) first; one empty lane, if any, last.
        availability: list[tuple[Any, int]] = []
        seen_tails: set[int] = set()
        for lane_idx, tail in enumerate(tails):
            if tail == -1 or tail in seen_tails:
                continue
            seen_tails.add(tail)
            required = gap_minutes(tail, i)
            if math.isinf(required):
                continue
            available_at = ends[tail] + timedelta(minutes=required)
            if available_at <= starts[i]:
                availability.append((available_at, lane_idx))
        candidates = [lane_idx for _avail, lane_idx in sorted(availability, reverse=True)]
        if -1 in tails:
            candidates.append(tails.index(-1))
        for lane_idx in candidates:
            new_tails = list(tails)
            new_tails[lane_idx] = i
            chosen.append((lane_idx, i))
            if search(i + 1, tuple(new_tails)):
                return True
            chosen.pop()
        visited.add(key)
        return False

    if not search(0, tuple([-1] * max_parallel)):
        return None
    lane_of = [0] * n
    for lane_idx, op_idx in chosen:
        lane_of[op_idx] = lane_idx
    return lane_of

if TYPE_CHECKING:
    from synaps.model import (
        Assignment,
        ScheduleProblem,
    )


# F7 (audit v4): bounds for the exact (memoized-backtracking) lane-assignment
# search on parallel machines. Beyond them the checker falls back to the legacy
# greedy inference (a heuristic — its infeasibility verdict is then UNPROVEN;
# the exact search's verdict is complete by construction).
_LANE_EXACT_MAX_OPS = 512
_LANE_EXACT_MAX_PARALLEL = 8
_LANE_EXACT_STATE_BUDGET = 200_000

#: Advisory kinds that flag checker uncertainty without proving a hard fault.
#: Callers that treat ``check`` as a boolean feasibility oracle should filter
#: these via :func:`hard_violations` (Wave 5 / KI-F7).
ADVISORY_VIOLATION_KINDS: frozenset[str] = frozenset({"LANE_INFERENCE_UNPROVEN"})

#: Hard kinds that, when emitted by the greedy lane path after a size/budget
#: fallback, justify accompanying ``LANE_INFERENCE_UNPROVEN``.
_GREEDY_UNPROVEN_TRIGGER_KINDS: frozenset[str] = frozenset(
    {
        "SETUP_GAP_VIOLATION",
        # MACHINE_CAPACITY_VIOLATION / MACHINE_OVERLAP are physical — never demote
        # them as lane-heuristic false positives (Wave 12 H12-1 / Wave 13 M13-1).
        "MISSING_SETUP_ENTRY",
    }
)


class FeasibilityViolation:
    """A single constraint violation."""

    def __init__(
        self, kind: str, message: str, operation_id: Any = None, work_center_id: Any = None
    ) -> None:
        self.kind = kind
        self.message = message
        self.operation_id = operation_id
        self.work_center_id = work_center_id

    def __repr__(self) -> str:
        return f"Violation({self.kind}: {self.message})"


@dataclass(frozen=True)
class NotaryScope:
    """Delta-notary filter. ``None`` fields mean the full family.

    Cardinality, referential integrity, and auxiliary TimeTable sweeps are
    never scoped. An empty frozenset skips that family. Parallel machines
    are never skipped even when absent from ``machine_ids``.
    """

    operation_ids: frozenset[Any] | None = None
    machine_ids: frozenset[Any] | None = None


def _op_in_scope(scope: NotaryScope | None, operation_id: Any) -> bool:
    if scope is None or scope.operation_ids is None:
        return True
    return operation_id in scope.operation_ids


def _skip_serial_unary(scope: NotaryScope | None, wc_id: Any, max_parallel: int) -> bool:
    if scope is None or scope.machine_ids is None or max_parallel > 1:
        return False
    return wc_id not in scope.machine_ids


def hard_violations(
    violations: list[FeasibilityViolation],
) -> list[FeasibilityViolation]:
    """Return violations that are not pure advisories (exclude ``LANE_INFERENCE_UNPROVEN``).

    Conservative filter used by BKS / diagnostic callers. When lane inference is
    unproven, greedy-trigger kinds may still be false positives — use
    :func:`proven_hard_violations` for the customer ``verified_feasible`` oracle.
    """
    return [v for v in violations if v.kind not in ADVISORY_VIOLATION_KINDS]


def proven_hard_violations(
    violations: list[FeasibilityViolation],
) -> list[FeasibilityViolation]:
    """Return violations that prove a constraint fault for customer feasibility.

    When ``LANE_INFERENCE_UNPROVEN`` is present on a work center, demotes
    greedy-fallback trigger kinds **only on that work center** (Wave 8 /
    RT17-H2 scoped by Wave 11 / H1). Unscoped ``LANE_INFERENCE_UNPROVEN``
    (``work_center_id is None``) retains the global demotion fallback.
    Hard faults on other machines remain proven.
    """
    scoped_unproven_wcs = {
        v.work_center_id
        for v in violations
        if v.kind == "LANE_INFERENCE_UNPROVEN" and v.work_center_id is not None
    }
    global_unproven = any(
        v.kind == "LANE_INFERENCE_UNPROVEN" and v.work_center_id is None for v in violations
    )
    proven: list[FeasibilityViolation] = []
    for violation in violations:
        if violation.kind in ADVISORY_VIOLATION_KINDS:
            continue
        if violation.kind in _GREEDY_UNPROVEN_TRIGGER_KINDS and (
            global_unproven or violation.work_center_id in scoped_unproven_wcs
        ):
            continue
        proven.append(violation)
    # W16b-1: if any work center was verified under unproven greedy lane
    # inference, the claim is UNKNOWN, not FEASIBLE. A greedy lane walk can
    # produce genuinely infeasible lane setups — demoting them was a
    # false-FEASIBLE hole on parallel machines at scale.
    if scoped_unproven_wcs or global_unproven:
        proven.append(
            FeasibilityViolation(
                "LANE_INFERENCE_UNPROVEN",
                "One or more work centers verified under greedy lane inference; "
                "setup-gap verdicts are unproven.",
                work_center_id=None,
            )
        )
    return proven


class FeasibilityChecker:
    """Check a set of assignments against the problem constraints.

    Checks performed (audit v4 numbering):
        1. All operations assigned exactly once (DUPLICATE_/MISSING_ASSIGNMENT).
        2. Assigned machine is in the eligible set (INELIGIBLE_MACHINE).
        3. Precedence respected (PRECEDENCE_VIOLATION).
        4. Per-machine no-overlap + capacity: serial machines and parallel lanes
           run the same setup-gap walk (MACHINE_OVERLAP, SETUP_GAP_VIOLATION,
           MISSING_SETUP_ENTRY under a strict matrix); parallel machines
           additionally enforce ``max_parallel`` via lane metadata or an EXACT
           memoized-backtracking lane inference (F7; greedy fallback beyond
           documented bounds) and a sweep-line over PHYSICAL occupancy windows
           ``[start - setup, end)`` (F1; emitted as MACHINE_CAPACITY_VIOLATION
           for both capacity-sweep and lane-count overflows).
        5. Auxiliary resource pools respected across setup + processing windows
           (AUX_RESOURCE_CAPACITY_VIOLATION).
        6. Horizon bounds (HORIZON_BOUND_VIOLATION).
        7. Release dates (RELEASE_DATE_VIOLATION).
        8. Durations cover the REAL processing time (base duration divided by
           machine speed — hard floor, no tolerance, F2; DURATION_MISMATCH).
           Under ``strict_grain=True``, spans below the canonical integer
           reservation grain are flagged as DURATION_BELOW_GRAIN.
    """

    @staticmethod
    def _lookup_required_setup(
        setup_lookup: dict[tuple[Any, Any, Any], int],
        *,
        work_center_id: Any,
        from_state_id: Any,
        to_state_id: Any,
        operation_id: Any,
        violations: list[FeasibilityViolation],
        exhaustive: bool,
        strict_setup_matrix: bool,
    ) -> int | None:
        """Return required setup minutes, or None when a blocking violation was recorded.

        Contract: absent setup cells default to 0 minutes (sparse SDST). When
        ``strict_setup_matrix`` is enabled, a missing *cross-state* cell is a
        hard ``MISSING_SETUP_ENTRY`` violation instead of a silent zero.
        """

        key = (work_center_id, from_state_id, to_state_id)
        if key in setup_lookup:
            return setup_lookup[key]
        if from_state_id == to_state_id or not strict_setup_matrix:
            return 0

        violations.append(
            FeasibilityViolation(
                "MISSING_SETUP_ENTRY",
                (
                    f"Machine {work_center_id} has no setup_matrix entry from state "
                    f"{from_state_id} to {to_state_id} for operation {operation_id}."
                ),
                operation_id=operation_id,
                work_center_id=work_center_id,
            )
        )
        if not exhaustive:
            return None
        return 10**9

    def _check_parallel_capacity(
        self,
        *,
        wc_id: Any,
        machine_assignments: list[Assignment],
        max_parallel: int,
        violations: list[FeasibilityViolation],
        exhaustive: bool,
        setup_window_start_by_op: dict[Any, Any],
    ) -> None:
        """Sweep-line usage check for a ``max_parallel > 1`` machine.

        F1 (audit v4): the occupancy window is PHYSICAL — it includes the
        right-justified setup window ``[start - setup, end)``, not just the
        processing span. The checker already accounts setup occupancy for
        auxiliary resources (see the aux-pool sweep); the machine itself must
        obey the same physics, otherwise a schedule whose setups spill over the
        lane count false-passes the capacity gate. Operations missing from
        ``setup_window_start_by_op`` (e.g. after a strict-matrix abort) fall
        back to their processing span.
        """
        events: list[tuple[Any, int, Any]] = []
        for assignment in machine_assignments:
            occupancy_start = setup_window_start_by_op.get(
                assignment.operation_id, assignment.start_time
            )
            events.append((occupancy_start, 1, assignment.operation_id))
            events.append((assignment.end_time, -1, assignment.operation_id))

        in_use = 0
        for timestamp, delta, operation_id in sorted(
            events, key=lambda item: (item[0], 0 if item[1] < 0 else 1)
        ):
            in_use += delta
            if in_use > max_parallel:
                violations.append(
                    FeasibilityViolation(
                        "MACHINE_CAPACITY_VIOLATION",
                        (
                            f"Machine {wc_id} exceeds max_parallel={max_parallel} "
                            f"at {timestamp}: "
                            f"usage is {in_use}."
                        ),
                        operation_id=operation_id,
                        work_center_id=wc_id,
                    )
                )
                if not exhaustive:
                    break

    def _lanes_from_metadata(
        self,
        *,
        wc_id: Any,
        machine_assignments: list[Assignment],
        max_parallel: int,
        violations: list[FeasibilityViolation],
    ) -> list[list[Assignment]]:
        """Group by explicit ``lane_id`` metadata; flag a lane-count overflow."""
        assignments_by_lane: dict[Any, list[Assignment]] = {}
        for assignment in machine_assignments:
            assignments_by_lane.setdefault(assignment.lane_id, []).append(assignment)
        if len(assignments_by_lane) > max_parallel:
            violations.append(
                FeasibilityViolation(
                    "MACHINE_CAPACITY_VIOLATION",
                    (
                        f"Machine {wc_id} exposes {len(assignments_by_lane)} lanes, "
                        f"exceeding max_parallel={max_parallel}."
                    ),
                    work_center_id=wc_id,
                )
            )
        return list(assignments_by_lane.values())

    def _choose_lane(
        self,
        *,
        wc_id: Any,
        assignment: Assignment,
        current_op: Any,
        lane_sequences: list[list[Assignment]],
        ops_by_id: dict[Any, Any],
        setup_lookup: dict[Any, Any],
        violations: list[FeasibilityViolation],
        exhaustive: bool,
        strict_setup_matrix: bool,
    ) -> tuple[int | None, bool]:
        """Pick the latest-available lane that fits setup-aware; None if none.

        Returns ``(lane_index, aborted)``.
        """
        chosen_lane_index: int | None = None
        chosen_available_at = None
        for lane_index, lane_assignments in enumerate(lane_sequences):
            lane_previous_assignment = lane_assignments[-1]
            previous_op = ops_by_id.get(lane_previous_assignment.operation_id)
            if previous_op is None:
                continue
            required_setup = self._lookup_required_setup(
                setup_lookup,
                work_center_id=wc_id,
                from_state_id=previous_op.state_id,
                to_state_id=current_op.state_id,
                operation_id=assignment.operation_id,
                violations=violations,
                exhaustive=exhaustive,
                strict_setup_matrix=strict_setup_matrix,
            )
            if required_setup is None:
                return None, True
            available_at = lane_previous_assignment.end_time + timedelta(
                minutes=required_setup
            )
            if available_at <= assignment.start_time and (
                chosen_available_at is None or available_at > chosen_available_at
            ):
                chosen_lane_index = lane_index
                chosen_available_at = available_at
        return chosen_lane_index, False

    def _lane_gap_minutes(
        self,
        *,
        wc_id: Any,
        from_state_id: Any,
        to_state_id: Any,
        setup_lookup: dict[Any, Any],
        strict_setup_matrix: bool,
    ) -> float:
        """Setup minutes required before a lane tail admits the next operation.

        Violation-free variant of ``_lookup_required_setup`` for the exact lane
        search: a missing cross-state cell under ``strict_setup_matrix`` is a
        FORBIDDEN transition (``inf``), not a recorded violation — diagnostics
        stay with the greedy path.
        """
        key = (wc_id, from_state_id, to_state_id)
        if key in setup_lookup:
            return float(setup_lookup[key])
        if from_state_id == to_state_id or not strict_setup_matrix:
            return 0.0
        return math.inf

    def _assign_lanes_exact(
        self,
        *,
        wc_id: Any,
        ordered: list[Assignment],
        max_parallel: int,
        ops_by_id: dict[Any, Any],
        setup_lookup: dict[Any, Any],
        strict_setup_matrix: bool,
    ) -> tuple[list[list[Assignment]] | None, bool]:
        """Exact lane assignment via memoized backtracking (F7).

        Processing operations in ``(start, end)`` order and branching over
        every admissible lane explores ALL lane assignments consistent with the
        time order, so a ``None`` result is a PROVEN infeasibility — unlike the
        greedy heuristic, which cannot distinguish "no assignment exists" from
        "my choices were unlucky". Lane interchangeability is quotiented out by
        canonically sorting the tail vector before memoization (in the engine,
        ``_exact_lane_assignment``).

        Returns ``(lanes, budget_exhausted)``; on budget exhaustion ``lanes``
        is ``None`` and the caller must fall back to the greedy heuristic.
        """
        known = [a for a in ordered if a.operation_id in ops_by_id]
        states = [ops_by_id[a.operation_id].state_id for a in known]
        ends = [a.end_time for a in known]
        starts = [a.start_time for a in known]

        def gap_minutes(from_idx: int, to_idx: int) -> float:
            return self._lane_gap_minutes(
                wc_id=wc_id,
                from_state_id=states[from_idx],
                to_state_id=states[to_idx],
                setup_lookup=setup_lookup,
                strict_setup_matrix=strict_setup_matrix,
            )

        try:
            lane_of = _exact_lane_assignment(starts, ends, gap_minutes, max_parallel)
        except _LaneSearchBudgetExceeded:
            return None, True
        if lane_of is None:
            return None, False

        lanes: list[list[Assignment]] = [[] for _ in range(max_parallel)]
        for op_idx, lane_idx in enumerate(lane_of):
            lanes[lane_idx].append(known[op_idx])
        return [lane for lane in lanes if lane], False

    def _build_lane_sequences(
        self,
        *,
        wc_id: Any,
        machine_assignments: list[Assignment],
        max_parallel: int,
        ops_by_id: dict[Any, Any],
        setup_lookup: dict[Any, Any],
        violations: list[FeasibilityViolation],
        exhaustive: bool,
        strict_setup_matrix: bool,
    ) -> tuple[list[list[Assignment]], bool]:
        """Group a parallel machine's assignments into per-lane serial sequences.

        Uses explicit ``lane_id`` metadata when every assignment carries it;
        otherwise infers lanes. F7 (audit v4): inference is EXACT (memoized
        backtracking, ``_assign_lanes_exact``) within documented bounds, so a
        SETUP_GAP_VIOLATION is a proven infeasibility, not a greedy artifact;
        beyond the bounds the legacy greedy heuristic runs (verdict unproven).
        Returns ``(lane_sequences, aborted)`` where ``aborted`` means the whole
        check must stop (strict setup-matrix miss in non-exhaustive mode).
        """
        if all(assignment.lane_id is not None for assignment in machine_assignments):
            return self._lanes_from_metadata(
                wc_id=wc_id,
                machine_assignments=machine_assignments,
                max_parallel=max_parallel,
                violations=violations,
            ), False

        inference_unproven = False
        if (
            len(machine_assignments) <= _LANE_EXACT_MAX_OPS
            and max_parallel <= _LANE_EXACT_MAX_PARALLEL
        ):
            ordered = sorted(
                machine_assignments,
                key=lambda item: (item.start_time, item.end_time),
            )
            exact_lanes, budget_exhausted = self._assign_lanes_exact(
                wc_id=wc_id,
                ordered=ordered,
                max_parallel=max_parallel,
                ops_by_id=ops_by_id,
                setup_lookup=setup_lookup,
                strict_setup_matrix=strict_setup_matrix,
            )
            if exact_lanes is not None:
                return exact_lanes, False
            if not budget_exhausted:
                # Proven infeasible: run the greedy walk purely to surface the
                # legacy diagnostics (MISSING_SETUP_ENTRY / SETUP_GAP_VIOLATION)
                # and to derive lanes for the downstream aux-window math.
                return self._assign_lanes_greedy(
                    wc_id=wc_id,
                    machine_assignments=machine_assignments,
                    max_parallel=max_parallel,
                    ops_by_id=ops_by_id,
                    setup_lookup=setup_lookup,
                    violations=violations,
                    exhaustive=exhaustive,
                    strict_setup_matrix=strict_setup_matrix,
                )
            # Budget exhausted: fall through to the greedy heuristic, whose
            # verdict is unproven (documented F7 bound).
            inference_unproven = True
        else:
            # Size / parallelism beyond the exact-search envelope (KI-F7).
            inference_unproven = True

        before = len(violations)
        lanes, aborted = self._assign_lanes_greedy(
            wc_id=wc_id,
            machine_assignments=machine_assignments,
            max_parallel=max_parallel,
            ops_by_id=ops_by_id,
            setup_lookup=setup_lookup,
            violations=violations,
            exhaustive=exhaustive,
            strict_setup_matrix=strict_setup_matrix,
        )
        if inference_unproven and any(
            v.kind in _GREEDY_UNPROVEN_TRIGGER_KINDS and v.work_center_id == wc_id
            for v in violations[before:]
        ):
            violations.append(
                FeasibilityViolation(
                    "LANE_INFERENCE_UNPROVEN",
                    (
                        f"Machine {wc_id}: lane inference used the greedy fallback "
                        f"(n={len(machine_assignments)}, max_parallel={max_parallel} "
                        f"exceeded exact bounds or exhausted the state budget); "
                        f"hard lane/setup violations on this machine are UNPROVEN."
                    ),
                    work_center_id=wc_id,
                )
            )
        return lanes, aborted

    def _assign_lanes_greedy(
        self,
        *,
        wc_id: Any,
        machine_assignments: list[Assignment],
        max_parallel: int,
        ops_by_id: dict[Any, Any],
        setup_lookup: dict[Any, Any],
        violations: list[FeasibilityViolation],
        exhaustive: bool,
        strict_setup_matrix: bool,
    ) -> tuple[list[list[Assignment]], bool]:
        """Legacy greedy lane inference (heuristic, order-dependent).

        Kept as the fallback beyond the exact-search bounds (F7) and as the
        diagnostics producer when the exact search proves infeasibility.
        """
        lane_sequences: list[list[Assignment]] = []
        for assignment in sorted(
            machine_assignments,
            key=lambda item: (item.start_time, item.end_time),
        ):
            current_op = ops_by_id.get(assignment.operation_id)
            if current_op is None:
                continue

            chosen_lane_index, aborted = self._choose_lane(
                wc_id=wc_id,
                assignment=assignment,
                current_op=current_op,
                lane_sequences=lane_sequences,
                ops_by_id=ops_by_id,
                setup_lookup=setup_lookup,
                violations=violations,
                exhaustive=exhaustive,
                strict_setup_matrix=strict_setup_matrix,
            )
            if aborted:
                return lane_sequences, True

            if chosen_lane_index is None:
                if len(lane_sequences) < max_parallel:
                    lane_sequences.append([assignment])
                    continue
                violations.append(
                    FeasibilityViolation(
                        "SETUP_GAP_VIOLATION",
                        (
                            f"Machine {wc_id} cannot place operation "
                            f"{assignment.operation_id} within max_parallel="
                            f"{max_parallel} while respecting setup gaps."
                        ),
                        operation_id=assignment.operation_id,
                        work_center_id=wc_id,
                    )
                )
                if not exhaustive:
                    break
                continue

            lane_sequences[chosen_lane_index].append(assignment)
        return lane_sequences, False

    def _check_sequence_setup_gaps(
        self,
        *,
        wc_id: Any,
        sequence: list[Assignment],
        ops_by_id: dict[Any, Any],
        setup_lookup: dict[Any, Any],
        violations: list[FeasibilityViolation],
        setup_window_start_by_op: dict[Any, Any],
        exhaustive: bool,
        strict_setup_matrix: bool,
    ) -> bool:
        """Overlap + setup-gap walk over ONE serial sequence (a serial machine
        or one virtual lane) -- previously two near-duplicate blocks in
        ``check``. Returns ``True`` when the whole check must stop (strict
        setup-matrix miss in non-exhaustive mode).
        """
        previous_assignment: Assignment | None = None
        for assignment in sorted(sequence, key=lambda item: item.start_time):
            if previous_assignment is None:
                setup_window_start_by_op[assignment.operation_id] = assignment.start_time
                previous_assignment = assignment
                continue

            if previous_assignment.end_time > assignment.start_time:
                violations.append(
                    FeasibilityViolation(
                        "MACHINE_OVERLAP",
                        "Overlap on machine "
                        f"{wc_id}: {previous_assignment.operation_id} ends after "
                        f"{assignment.operation_id} starts.",
                        work_center_id=wc_id,
                    )
                )
                previous_assignment = assignment
                continue

            previous_op = ops_by_id.get(previous_assignment.operation_id)
            current_op = ops_by_id.get(assignment.operation_id)
            required_setup = 0
            if previous_op is not None and current_op is not None:
                looked_up = self._lookup_required_setup(
                    setup_lookup,
                    work_center_id=wc_id,
                    from_state_id=previous_op.state_id,
                    to_state_id=current_op.state_id,
                    operation_id=assignment.operation_id,
                    violations=violations,
                    exhaustive=exhaustive,
                    strict_setup_matrix=strict_setup_matrix,
                )
                if looked_up is None:
                    return True
                required_setup = looked_up

            actual_gap_minutes = (
                assignment.start_time - previous_assignment.end_time
            ).total_seconds() / 60.0
            if actual_gap_minutes < required_setup:
                violations.append(
                    FeasibilityViolation(
                        "SETUP_GAP_VIOLATION",
                        (
                            f"Machine {wc_id} requires {required_setup} minutes of "
                            f"setup between {previous_assignment.operation_id} and "
                            f"{assignment.operation_id}, but only "
                            f"{actual_gap_minutes:.1f} minutes are available."
                        ),
                        operation_id=assignment.operation_id,
                        work_center_id=wc_id,
                    )
                )

            setup_window_start_by_op[assignment.operation_id] = (
                assignment.start_time - timedelta(minutes=required_setup)
            )
            previous_assignment = assignment
        return False

    @staticmethod
    def _fill_serial_setup_windows_from_stamps(
        machine_assignments: list[Assignment],
        setup_window_start_by_op: dict[Any, Any],
    ) -> None:
        """Lemma A: skipped serial sequences still need F1 occupancy starts."""

        ordered = sorted(machine_assignments, key=lambda item: item.start_time)
        for index, assignment in enumerate(ordered):
            if index == 0:
                setup_window_start_by_op[assignment.operation_id] = assignment.start_time
                continue
            setup_window_start_by_op[assignment.operation_id] = (
                assignment.start_time - timedelta(minutes=assignment.setup_minutes)
            )

    @staticmethod
    def _check_aux_pools(
        *,
        assignments: list[Assignment],
        resources_by_id: dict[Any, Any],
        requirements_by_op: dict[Any, list[Any]],
        setup_window_start_by_op: dict[Any, Any],
        violations: list[FeasibilityViolation],
        exhaustive: bool,
    ) -> None:
        """Full TimeTable sweep. Never scoped (accel RFC A4 / Lemma A)."""

        for resource_id, resource in resources_by_id.items():
            resource_events: list[tuple[Any, int, Any]] = []
            for assignment in assignments:
                for requirement in requirements_by_op.get(assignment.operation_id, []):
                    if requirement.aux_resource_id != resource_id:
                        continue
                    resource_events.append(
                        (
                            setup_window_start_by_op.get(
                                assignment.operation_id, assignment.start_time
                            ),
                            requirement.quantity_needed,
                            assignment.operation_id,
                        )
                    )
                    resource_events.append(
                        (assignment.end_time, -requirement.quantity_needed, assignment.operation_id)
                    )
            in_use = 0
            for timestamp, delta, operation_id in sorted(
                resource_events, key=lambda item: (item[0], 0 if item[1] < 0 else 1)
            ):
                in_use += delta
                if in_use > resource.pool_size:
                    violations.append(
                        FeasibilityViolation(
                            "AUX_RESOURCE_CAPACITY_VIOLATION",
                            (
                                f"Auxiliary resource {resource.code} exceeds pool size "
                                f"{resource.pool_size} "
                                f"at {timestamp}: usage is {in_use}."
                            ),
                            operation_id=operation_id,
                        )
                    )
                    if not exhaustive:
                        break

    def check(
        self,
        problem: ScheduleProblem,
        assignments: list[Assignment],
        *,
        exhaustive: bool = False,
        strict_setup_matrix: bool = False,
        strict_grain: bool = False,
        scope: NotaryScope | None = None,
    ) -> list[FeasibilityViolation]:
        violations: list[FeasibilityViolation] = []
        ops_by_id = {op.id: op for op in problem.operations}
        orders_by_id = {order.id: order for order in problem.orders}
        work_centers_by_id = {work_center.id: work_center for work_center in problem.work_centers}
        setup_lookup = {
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
            for entry in problem.setup_matrix
        }
        resources_by_id = {resource.id: resource for resource in problem.auxiliary_resources}
        requirements_by_op: dict[Any, list[Any]] = {}
        for requirement in problem.aux_requirements:
            requirements_by_op.setdefault(requirement.operation_id, []).append(requirement)
        assigned: dict[Any, Assignment] = {}

        # 1. All operations assigned exactly once
        for a in assignments:
            if a.operation_id in assigned:
                violations.append(
                    FeasibilityViolation(
                        "DUPLICATE_ASSIGNMENT",
                        f"Operation {a.operation_id} assigned more than once.",
                        operation_id=a.operation_id,
                    )
                )
            assigned[a.operation_id] = a

        for op in problem.operations:
            if op.id not in assigned:
                violations.append(
                    FeasibilityViolation(
                        "MISSING_ASSIGNMENT",
                        f"Operation {op.id} not assigned.",
                        operation_id=op.id,
                    )
                )

        # 1b. Referential integrity of the RESULT itself (RT-20): phantom
        # operation / work-center references must not be certified.
        self._check_referential_integrity(assignments, ops_by_id, work_centers_by_id, violations)

        # 2. Eligible machine
        for a in assignments:
            if not _op_in_scope(scope, a.operation_id):
                continue
            assigned_op = ops_by_id.get(a.operation_id)
            if (
                assigned_op
                and assigned_op.eligible_wc_ids
                and a.work_center_id not in assigned_op.eligible_wc_ids
            ):
                violations.append(
                    FeasibilityViolation(
                        "INELIGIBLE_MACHINE",
                        "Operation "
                        f"{a.operation_id} assigned to ineligible machine {a.work_center_id}.",
                        operation_id=a.operation_id,
                        work_center_id=a.work_center_id,
                    )
                )

        # 3. Precedence
        for op in problem.operations:
            if (
                scope is not None
                and scope.operation_ids is not None
                and op.id not in scope.operation_ids
                and (
                    op.predecessor_op_id is None
                    or op.predecessor_op_id not in scope.operation_ids
                )
            ):
                continue
            if op.predecessor_op_id and op.id in assigned and op.predecessor_op_id in assigned:
                pred_end = assigned[op.predecessor_op_id].end_time
                cur_start = assigned[op.id].start_time
                if cur_start < pred_end:
                    violations.append(
                        FeasibilityViolation(
                            "PRECEDENCE_VIOLATION",
                            "Operation "
                            f"{op.id} starts at {cur_start} before predecessor ends at {pred_end}.",
                            operation_id=op.id,
                        )
                    )

        # 4. No overlap per machine: parallel machines get per-lane sequences
        # (which fill the right-justified setup windows) and then a sweep-line
        # capacity check over PHYSICAL occupancy windows (setup + processing,
        # F1); every sequence (a lane, or the whole serial machine) runs the
        # SAME overlap/setup-gap walk.
        by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            by_machine.setdefault(a.work_center_id, []).append(a)

        setup_window_start_by_op: dict[Any, Any] = {}

        for wc_id, machine_assignments in by_machine.items():
            work_center = work_centers_by_id.get(wc_id)
            max_parallel = work_center.max_parallel if work_center is not None else 1
            if _skip_serial_unary(scope, wc_id, max_parallel):
                self._fill_serial_setup_windows_from_stamps(
                    machine_assignments, setup_window_start_by_op
                )
                continue

            if max_parallel > 1:
                lane_sequences, aborted = self._build_lane_sequences(
                    wc_id=wc_id,
                    machine_assignments=machine_assignments,
                    max_parallel=max_parallel,
                    ops_by_id=ops_by_id,
                    setup_lookup=setup_lookup,
                    violations=violations,
                    exhaustive=exhaustive,
                    strict_setup_matrix=strict_setup_matrix,
                )
                if aborted:
                    return violations
                sequences = lane_sequences
            else:
                sequences = [machine_assignments]

            for sequence in sequences:
                if self._check_sequence_setup_gaps(
                    wc_id=wc_id,
                    sequence=sequence,
                    ops_by_id=ops_by_id,
                    setup_lookup=setup_lookup,
                    violations=violations,
                    setup_window_start_by_op=setup_window_start_by_op,
                    exhaustive=exhaustive,
                    strict_setup_matrix=strict_setup_matrix,
                ):
                    return violations

            if max_parallel > 1:
                # Runs AFTER the per-lane walks so the sweep can charge the
                # physical occupancy window [start - setup, end) (F1).
                self._check_parallel_capacity(
                    wc_id=wc_id,
                    machine_assignments=machine_assignments,
                    max_parallel=max_parallel,
                    violations=violations,
                    exhaustive=exhaustive,
                    setup_window_start_by_op=setup_window_start_by_op,
                )

        # 5. Auxiliary resource pools — full TimeTable, never scoped (Lemma A).
        self._check_aux_pools(
            assignments=assignments,
            resources_by_id=resources_by_id,
            requirements_by_op=requirements_by_op,
            setup_window_start_by_op=setup_window_start_by_op,
            violations=violations,
            exhaustive=exhaustive,
        )

        # 6. Horizon bounds
        for a in assignments:
            if not _op_in_scope(scope, a.operation_id):
                continue
            if a.start_time < problem.planning_horizon_start:
                violations.append(
                    FeasibilityViolation(
                        "HORIZON_BOUND_VIOLATION",
                        (
                            f"Operation {a.operation_id} starts at {a.start_time}, "
                            f"before planning horizon start {problem.planning_horizon_start}."
                        ),
                        operation_id=a.operation_id,
                    )
                )
            if a.end_time > problem.planning_horizon_end:
                violations.append(
                    FeasibilityViolation(
                        "HORIZON_BOUND_VIOLATION",
                        (
                            f"Operation {a.operation_id} ends at {a.end_time}, "
                            f"after planning horizon end {problem.planning_horizon_end}."
                        ),
                        operation_id=a.operation_id,
                    )
                )

        scoped_ops = None if scope is None else scope.operation_ids
        self._check_release_and_op_windows(
            assignments=assignments,
            ops_by_id=ops_by_id,
            orders_by_id=orders_by_id,
            violations=violations,
            exhaustive=exhaustive,
            operation_ids=scoped_ops,
        )

        # 8. Operation durations (P0-3; hardened by F2, audit v4 — see the
        # helper's docstring for the physical-floor contract).
        self._check_durations(
            assignments=assignments,
            ops_by_id=ops_by_id,
            work_centers_by_id=work_centers_by_id,
            violations=violations,
            exhaustive=exhaustive,
            strict_grain=strict_grain,
            operation_ids=scoped_ops,
        )

        return violations

    @staticmethod
    def _check_release_and_op_windows(
        *,
        assignments: list[Assignment],
        ops_by_id: dict[Any, Any],
        orders_by_id: dict[Any, Any],
        violations: list[FeasibilityViolation],
        exhaustive: bool,
        operation_ids: frozenset[Any] | None = None,
    ) -> None:
        """Order release_date plus optional per-op earliest_start / latest_finish."""

        for assignment in assignments:
            if operation_ids is not None and assignment.operation_id not in operation_ids:
                continue
            checked_op = ops_by_id.get(assignment.operation_id)
            if checked_op is None:
                continue
            order = orders_by_id.get(checked_op.order_id)
            release = getattr(order, "release_date", None) if order is not None else None
            if release is not None and assignment.start_time < release:
                violations.append(
                    FeasibilityViolation(
                        "RELEASE_DATE_VIOLATION",
                        (
                            f"Operation {assignment.operation_id} starts at "
                            f"{assignment.start_time}, before order release_date {release}."
                        ),
                        operation_id=assignment.operation_id,
                    )
                )
                if not exhaustive:
                    return
            earliest = getattr(checked_op, "earliest_start", None)
            if earliest is not None and assignment.start_time < earliest:
                violations.append(
                    FeasibilityViolation(
                        "RELEASE_DATE_VIOLATION",
                        (
                            f"Operation {assignment.operation_id} starts at "
                            f"{assignment.start_time}, before earliest_start {earliest}."
                        ),
                        operation_id=assignment.operation_id,
                    )
                )
                if not exhaustive:
                    return
            latest = getattr(checked_op, "latest_finish", None)
            if latest is not None and assignment.end_time > latest:
                violations.append(
                    FeasibilityViolation(
                        "HORIZON_BOUND_VIOLATION",
                        (
                            f"Operation {assignment.operation_id} ends at "
                            f"{assignment.end_time}, after latest_finish {latest}."
                        ),
                        operation_id=assignment.operation_id,
                    )
                )
                if not exhaustive:
                    return

    @staticmethod
    def _check_referential_integrity(
        assignments: list[Assignment],
        ops_by_id: dict[Any, Any],
        work_centers_by_id: dict[Any, Any],
        violations: list[FeasibilityViolation],
    ) -> None:
        """Every assignment must reference entities that exist in the problem
        (RT-20). Phantom rows previously skipped the eligibility / release /
        duration checks silently and were only caught if they happened to
        overlap on a real machine — a notary must reject them outright."""
        for a in assignments:
            if a.operation_id not in ops_by_id:
                violations.append(
                    FeasibilityViolation(
                        "UNKNOWN_OPERATION",
                        f"Assignment references operation {a.operation_id} "
                        "that is not part of the problem.",
                        operation_id=a.operation_id,
                    )
                )
            if a.work_center_id not in work_centers_by_id:
                violations.append(
                    FeasibilityViolation(
                        "UNKNOWN_WORK_CENTER",
                        f"Assignment references work center {a.work_center_id} "
                        "that is not part of the problem.",
                        operation_id=a.operation_id,
                        work_center_id=a.work_center_id,
                    )
                )

    @staticmethod
    def _check_durations(
        *,
        assignments: list[Assignment],
        ops_by_id: dict[Any, Any],
        work_centers_by_id: dict[Any, Any],
        violations: list[FeasibilityViolation],
        exhaustive: bool,
        strict_grain: bool,
        operation_ids: frozenset[Any] | None = None,
    ) -> None:
        """Duration adequacy check (P0-3; hardened by F2, audit v4).

        The assignment span must cover the operation's REAL processing time
        (:func:`synaps.timegrain.physical_processing_minutes_for` — override or
        base/speed): a shorter span is physically impossible and is a hard
        DURATION_MISMATCH with NO tolerance.

        History: the pre-v4 checker kept a 1-minute slop around the canonical
        ceil grain to absorb solver-side round/raw-float divergence, and its
        comment claimed round(base/speed) >= base/speed — false whenever the
        fractional part is < 0.5, so the checker certified physically
        impossible spans (up to 0.5 min under-reservation per op, compounding
        along precedence chains). T-10 removed the divergence at the source
        (ALNS native repair/seed now snap to the canonical ceil grain), so the
        tolerance is gone.

        Solvers reserve the canonical integer grain via
        :func:`synaps.timegrain.duration_minutes_for` (P0-4 / T-30). A span
        at/above the physical floor but below the grain is
        feasible-but-off-grain and is flagged as DURATION_BELOW_GRAIN only
        under ``strict_grain=True`` (grain policy is a solver obligation;
        physical sufficiency is the checker's).
        """
        for a in assignments:
            if operation_ids is not None and a.operation_id not in operation_ids:
                continue
            checked_op = ops_by_id.get(a.operation_id)
            if checked_op is None:
                continue
            work_center = work_centers_by_id.get(a.work_center_id)
            if work_center is None:
                continue
            span = (a.end_time - a.start_time).total_seconds() / 60.0
            physical = physical_processing_minutes_for(checked_op, work_center)
            if span + 1e-9 < physical:
                violations.append(
                    FeasibilityViolation(
                        "DURATION_MISMATCH",
                        (
                            f"Operation {a.operation_id} span {span:.6g} min is below "
                            f"physical processing floor {physical:.6g} min on "
                            f"work center {a.work_center_id}."
                        ),
                        operation_id=a.operation_id,
                        work_center_id=a.work_center_id,
                    )
                )
                if not exhaustive:
                    return
            if strict_grain:
                expected = duration_minutes_for(checked_op, work_center)
                if span + 1e-9 < float(expected):
                    violations.append(
                        FeasibilityViolation(
                            "DURATION_BELOW_GRAIN",
                            (
                                f"Operation {a.operation_id} span {span:.6g} min is below "
                                f"canonical grain {expected} min on work center "
                                f"{a.work_center_id}."
                            ),
                            operation_id=a.operation_id,
                            work_center_id=a.work_center_id,
                        )
                    )
                    if not exhaustive:
                        return
