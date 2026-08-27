"""Independent notary recheck of a stored schedule (K3.4).

Hashed COVER/deadzone run JSON typically has no assignment list. Those
artifacts are not recheckable; ``verified_feasible`` on them stays a
self-report. Recheck requires a problem plus nonempty assignments.
"""

from __future__ import annotations

from typing import Any

from synaps.model import ScheduleProblem, ScheduleResult, SolverStatus
from synaps.validation import SolutionVerification, verify_schedule_result


def result_from_payload(payload: dict[str, Any]) -> ScheduleResult | None:
    """Build a ``ScheduleResult`` when *payload* carries assignments."""

    raw_assignments = payload.get("assignments")
    if not isinstance(raw_assignments, list) or not raw_assignments:
        return None
    first = raw_assignments[0]
    if not isinstance(first, dict) or "operation_id" not in first:
        return None
    status_raw = payload.get("status")
    try:
        status = SolverStatus(str(status_raw)) if status_raw else SolverStatus.ERROR
    except ValueError:
        status = SolverStatus.ERROR
    return ScheduleResult.model_validate(
        {
            "solver_name": payload.get("solver_name") or payload.get("solver_config") or "recheck",
            "status": status,
            "assignments": raw_assignments,
        }
    )


def recheck_problem_and_payload(
    problem: ScheduleProblem,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return a JSON-ready recheck report. Never rewrites *payload*."""

    result = result_from_payload(payload)
    if result is None:
        return {
            "recheckable": False,
            "reason": "no_assignments",
            "verified_feasible": None,
            "violation_kinds": [],
            "violation_count": 0,
        }
    # Independent notary: do not trust client status. verify_schedule_result
    # skips the checker when status is not FEASIBLE/OPTIMAL.
    probe = result.model_copy(update={"status": SolverStatus.FEASIBLE})
    verification: SolutionVerification = verify_schedule_result(problem, probe)
    return {
        "recheckable": True,
        "reason": None,
        "client_status": result.status.value,
        "verified_feasible": verification.feasible,
        "violation_kinds": verification.violation_kinds,
        "violation_count": verification.violation_count,
        "violation_kind_counts": verification.violation_kind_counts,
    }
