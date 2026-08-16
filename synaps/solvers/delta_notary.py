"""Delta notary: scoped re-check after IncrementalRepair.

Completeness sketch (tested by McKeeman differential vs exhaustive):

Let B be the baseline assignment map and R the repaired map. Let C be the
operations whose ``(wc, start, end, setup, aux, lane)`` stamp differs, plus
ids present on only one side, plus ops whose occupancy window
``[start - setup, end)`` contains ``freeze_horizon_end`` when given.

**Lemma U (unary / disjunctive).** Overlap and SDST on machine m depend only
on the ordered sequence on m (Vilím Θ-tree overload is the *search* analogue,
CPAIOR 2004; we do not ship a Θ-tree). If no assignment on m changed, the
sequence is identical. Dirty machines = work centers appearing in B[o] or
R[o] for o in C. Parallel machines (``max_parallel > 1``) are never skipped:
lane inference is not stamp-fillable.

**Lemma P (precedence).** Edge pred→o depends only on R[pred].end and
R[o].start. Incident edges of C suffice.

**Lemma O (per-op).** Duration, release, horizon, eligible depend only on
R[o]. If o not in C, skip.

**Lemma A (aux Cumulative).** Occupancy of pool p at t is the sum of *all*
ops using p that overlap t (TimeTable / profile; Wolf & Schrader INAP 2005
O(n log n) cumulative overload). A neighbourhood slice is unsound when many
ops share one pool (accel RFC A4: one drum pool). Delta therefore always
runs the full event sweep. Occupancy starts on skipped *serial* machines are
filled from assignment setup stamps so the sweep is not truncated to
processing spans.

**Lemma C (cardinality).** Missing/duplicate and referential integrity use
the full id sets. Always O(n).

**Lemma I (inductive baseline).** Skipping unchanged serial machines means
delta ≡ exhaustive(R) only if those sequences were already feasible in B,
*or* the caller does not care about inherited infeasibility. IncrementalRepair
runs after a COVER notary. ``shadow`` fail-closes on mismatch: the FEASIBLE
claim uses exhaustive. Default remains exhaustive until a nervous-month
shadow probe is clean on both seeds; this module does not flip the default.

A one-shot post-repair notary on a single Cumulative pool is already
O(n log n) for aux. A segment tree would pay off for repeated insert/delete
during search, not this call site. We do not fake one.

Oracle: McKeeman, *Differential testing for software*, Digital Technical
Journal 10(1):100-107, 1998. Exhaustive ``FeasibilityChecker.check`` is the
reference implementation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from synaps.solvers.feasibility_checker import (
    FeasibilityChecker,
    FeasibilityViolation,
    NotaryScope,
    proven_hard_violations,
)

if TYPE_CHECKING:
    from synaps.model import Assignment, ScheduleProblem

NOTARY_MODES: frozenset[str] = frozenset({"exhaustive", "delta", "shadow"})


@dataclass(frozen=True)
class NotaryOutcome:
    """Claim violations plus honesty stamps. FEASIBLE uses ``violations``."""

    violations: list[FeasibilityViolation]
    mode: str
    mismatch: bool
    elapsed_ms: int
    dirty_operations: int
    dirty_machines: int


def _assignment_stamp(assignment: Assignment) -> tuple[Any, ...]:
    return (
        assignment.work_center_id,
        assignment.start_time,
        assignment.end_time,
        int(assignment.setup_minutes),
        tuple(assignment.aux_resource_ids),
        assignment.lane_id,
    )


def _index_last(assignments: list[Assignment]) -> dict[Any, Assignment]:
    return {assignment.operation_id: assignment for assignment in assignments}


def _touches_freeze(assignment: Assignment, freeze_end: datetime) -> bool:
    occupancy_start = assignment.start_time - timedelta(minutes=assignment.setup_minutes)
    return occupancy_start < freeze_end < assignment.end_time


def _build_notary_scope(
    baseline: list[Assignment],
    repaired: list[Assignment],
    *,
    freeze_horizon_end: datetime | None = None,
) -> NotaryScope:
    """Dirty ops/machines. Superset of stamp changes; still incomplete without Lemma I."""

    before = _index_last(baseline)
    after = _index_last(repaired)
    dirty_ops: set[Any] = set(before) ^ set(after)
    for operation_id in set(before) & set(after):
        if _assignment_stamp(before[operation_id]) != _assignment_stamp(after[operation_id]):
            dirty_ops.add(operation_id)
    if freeze_horizon_end is not None:
        for assignment in repaired:
            if _touches_freeze(assignment, freeze_horizon_end):
                dirty_ops.add(assignment.operation_id)
    dirty_machines: set[Any] = set()
    for operation_id in dirty_ops:
        previous = before.get(operation_id)
        current = after.get(operation_id)
        if previous is not None:
            dirty_machines.add(previous.work_center_id)
        if current is not None:
            dirty_machines.add(current.work_center_id)
    return NotaryScope(
        operation_ids=frozenset(dirty_ops),
        machine_ids=frozenset(dirty_machines),
    )


def _violation_fingerprint(
    violations: list[FeasibilityViolation],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted((item.kind, str(item.operation_id), str(item.work_center_id)) for item in violations)
    )


def _claim_violations(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    scope: NotaryScope | None,
) -> list[FeasibilityViolation]:
    raw = FeasibilityChecker().check(problem, assignments, exhaustive=True, scope=scope)
    return proven_hard_violations([item for item in raw if item.kind != "UNKNOWN_OPERATION"])


def notarize_repair(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    *,
    mode: str = "exhaustive",
    baseline: list[Assignment] | None = None,
    freeze_horizon_end: datetime | None = None,
) -> NotaryOutcome:
    """Return claim violations. Unknown/delta-without-baseline → exhaustive."""

    started = time.perf_counter()
    resolved = mode if mode in NOTARY_MODES else "exhaustive"
    baseline_list = list(baseline or [])
    use_delta = resolved in {"delta", "shadow"} and bool(baseline_list)
    if resolved == "delta" and not baseline_list:
        resolved = "exhaustive"
    scope = (
        _build_notary_scope(baseline_list, assignments, freeze_horizon_end=freeze_horizon_end)
        if use_delta
        else None
    )
    mismatch = False
    if resolved == "shadow" and use_delta:
        delta_hits = _claim_violations(problem, assignments, scope)
        hits = _claim_violations(problem, assignments, None)
        mismatch = _violation_fingerprint(delta_hits) != _violation_fingerprint(hits)
    elif use_delta:
        hits = _claim_violations(problem, assignments, scope)
    else:
        hits = _claim_violations(problem, assignments, None)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    dirty_ops = 0 if scope is None or scope.operation_ids is None else len(scope.operation_ids)
    dirty_wcs = 0 if scope is None or scope.machine_ids is None else len(scope.machine_ids)
    return NotaryOutcome(
        violations=hits,
        mode=resolved,
        mismatch=mismatch,
        elapsed_ms=elapsed_ms,
        dirty_operations=dirty_ops,
        dirty_machines=dirty_wcs,
    )
