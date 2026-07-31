"""Loader for the standard ``.fjs`` FJSP benchmark format.

Parses the classical flexible job-shop text format used by the public
benchmark suites (Brandimarte 1993 ``mk01``-``mk10``, Hurink et al. 1994
``edata``/``rdata``/``vdata``, Dauzère-Pérès & Paulli / DAFJS) into a
SynAPS :class:`~synaps.model.ScheduleProblem`.

Format (whitespace-separated; machine ids 1-indexed in the classical files,
0-indexed in some mirrors — the base is auto-detected per file, see below):

    line 1: <n_jobs> <n_machines> [<avg_machines_per_op>]
    then one line per job:
        <n_ops> { <n_alternatives> { <machine_id> <duration> } * } *

Mapping decisions (documented for benchmark comparability):

* No sequence-dependent setups exist in the format → empty
  ``setup_matrix`` and a single shared state (pure FJSP subset of
  MO-FJSP-SDST-ARC).
* No due dates exist in the format → every order's due date is set to
  the planning-horizon end, so tardiness is identically zero and the
  weighted objective reduces to makespan — matching how the public
  suites are scored (makespan minimisation).
* The planning horizon is the sum of every operation's maximum
  alternative duration (a trivially safe scheduling upper bound), so no
  feasible schedule is horizon-clipped.
* Durations are used verbatim as integer minutes; work-center
  ``speed_factor`` stays 1.0. Machine-dependent durations are expressed
  through per-operation eligibility: the SynAPS core models duration
  per operation, not per (operation, machine) pair, so heterogeneous
  alternatives are approximated by ``base_duration_min = min`` over the
  listed alternatives with eligibility restricted to the listed
  machines. The exact per-pair durations are preserved in
  ``domain_attributes["fjs_machine_durations"]`` for downstream exact
  solvers or reporting. This approximation is conservative for lower
  bounds and is reported in the instance metadata so published numbers
  are never silently compared against per-pair-exact suites.

The parser is strict: malformed token streams raise ``FjsParseError``
with the token index, never a silent partial instance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from synaps.model import Operation, Order, ScheduleProblem, State, WorkCenter

#: Public suites use minutes-scale integers; guard against absurd files.
MAX_FJS_TOKENS = 2_000_000

#: Per-operation duration sanity cap (~19 years in minutes). Durations above
#: this are rejected: they are malformed input, and unbounded accumulation
#: would overflow the ``timedelta`` horizon construction (DoS vector).
MAX_FJS_DURATION_MINUTES = 10_000_000

#: Aggregate-horizon sanity cap. ``timedelta`` tops out near 1.44e12 minutes
#: (999999999 days); stay comfortably below so summed durations across many
#: operations cannot overflow the horizon construction.
MAX_FJS_HORIZON_MINUTES = 1_000_000_000

_HORIZON_START = datetime(2026, 1, 1, tzinfo=UTC)


class FjsParseError(ValueError):
    """Raised when a ``.fjs`` token stream is malformed."""


class _TokenStream:
    """Strict integer token cursor over the whitespace-split file body."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self._index = 0

    @property
    def index(self) -> int:
        return self._index

    def remaining(self) -> int:
        return len(self._tokens) - self._index

    def next_int(self, *, context: str) -> int:
        if self._index >= len(self._tokens):
            raise FjsParseError(
                f"unexpected end of file while reading {context} (token #{self._index})"
            )
        raw = self._tokens[self._index]
        self._index += 1
        try:
            # Some suites emit float-looking averages ("2.0"); ints elsewhere.
            value = int(float(raw))
        except (ValueError, OverflowError) as exc:
            # OverflowError guards against "inf"/"Infinity" tokens, which
            # float() accepts but int() cannot convert.
            raise FjsParseError(
                f"non-numeric token {raw!r} while reading {context} (token #{self._index - 1})"
            ) from exc
        return value


def load_fjs_problem(path: Path | str) -> ScheduleProblem:
    """Parse *path* (standard ``.fjs`` file) into a ``ScheduleProblem``."""
    text = Path(path).read_text(encoding="utf-8")
    tokens = text.split()
    if not tokens:
        raise FjsParseError("empty .fjs file")
    if len(tokens) > MAX_FJS_TOKENS:
        raise FjsParseError(
            f".fjs file has {len(tokens)} tokens; exceeds supported maximum {MAX_FJS_TOKENS}"
        )

    stream = _TokenStream(tokens)
    n_jobs = stream.next_int(context="job count")
    n_machines = stream.next_int(context="machine count")
    if n_jobs <= 0 or n_machines <= 0:
        raise FjsParseError(f"invalid header: n_jobs={n_jobs}, n_machines={n_machines}")

    # Optional third header token: average machines per operation. Detect it
    # by look-ahead: for well-formed bodies the next token is the first job's
    # operation count, which is always >= 1; the average may be fractional and
    # is redundant, so we consume it only when the raw token contains a dot.
    if stream.remaining() > 0 and "." in tokens[stream.index]:
        stream.next_int(context="average machines per operation (ignored)")

    # Machine-id indexing base. The classical suites are 1-indexed
    # (1..n_machines) but several public mirrors (e.g.
    # SchedulingLab/fjsp-instances) re-emit the same instances 0-indexed
    # (0..n_machines-1). Auto-detect via a strict structural pre-pass over the
    # remaining tokens: walk the job/op/alternative grammar and collect every
    # machine reference, then decide the base. Mixed or out-of-range ids stay
    # hard errors — never a silent guess.
    body_start = stream.index
    machine_refs: list[int] = []
    for job_idx in range(n_jobs):
        n_ops = stream.next_int(context=f"operation count of job {job_idx + 1}")
        if n_ops <= 0:
            raise FjsParseError(f"job {job_idx + 1} declares {n_ops} operations")
        for op_idx in range(n_ops):
            n_alternatives = stream.next_int(
                context=f"alternative count of job {job_idx + 1} op {op_idx + 1}"
            )
            if n_alternatives <= 0:
                raise FjsParseError(
                    f"job {job_idx + 1} op {op_idx + 1} declares {n_alternatives} alternatives"
                )
            for alt_idx in range(n_alternatives):
                machine_refs.append(
                    stream.next_int(
                        context=(
                            f"machine id of job {job_idx + 1} op {op_idx + 1} "
                            f"alt {alt_idx + 1}"
                        )
                    )
                )
                stream.next_int(
                    context=f"duration of job {job_idx + 1} op {op_idx + 1} alt {alt_idx + 1}"
                )
    if not machine_refs:
        raise FjsParseError("no machine references found in body")
    min_ref, max_ref = min(machine_refs), max(machine_refs)
    if min_ref >= 1 and max_ref <= n_machines:
        machine_index_base = 1
    elif min_ref >= 0 and max_ref <= n_machines - 1:
        machine_index_base = 0
    else:
        raise FjsParseError(
            f"machine ids span {min_ref}..{max_ref}, consistent with neither "
            f"1..{n_machines} (1-indexed) nor 0..{n_machines - 1} (0-indexed)"
        )

    # Re-parse the body for real from the recorded start.
    stream = _TokenStream(tokens)
    stream._index = body_start

    shared_state = State(code="FJS-DEFAULT", label="single shared state (no SDST)")
    work_centers = [
        WorkCenter(code=f"M{machine_idx + 1}", capability_group="fjs")
        for machine_idx in range(n_machines)
    ]
    wc_id_by_index = {machine_idx: wc.id for machine_idx, wc in enumerate(work_centers)}

    orders: list[Order] = []
    operations: list[Operation] = []
    horizon_upper_bound_min = 0

    for job_idx in range(n_jobs):
        order_id = uuid4()
        n_ops = stream.next_int(context=f"operation count of job {job_idx + 1}")
        if n_ops <= 0:
            raise FjsParseError(f"job {job_idx + 1} declares {n_ops} operations")

        previous_op_id = None
        for op_idx in range(n_ops):
            n_alternatives = stream.next_int(
                context=f"alternative count of job {job_idx + 1} op {op_idx + 1}"
            )
            if n_alternatives <= 0:
                raise FjsParseError(
                    f"job {job_idx + 1} op {op_idx + 1} declares {n_alternatives} alternatives"
                )
            machine_durations: dict[str, int] = {}
            eligible_wc_ids = []
            for alt_idx in range(n_alternatives):
                machine_ref = stream.next_int(
                    context=(
                        f"machine id of job {job_idx + 1} op {op_idx + 1} alt {alt_idx + 1}"
                    )
                )
                duration = stream.next_int(
                    context=(
                        f"duration of job {job_idx + 1} op {op_idx + 1} alt {alt_idx + 1}"
                    )
                )
                if not machine_index_base <= machine_ref <= (
                    n_machines - 1 + machine_index_base
                ):
                    raise FjsParseError(
                        f"machine id {machine_ref} out of range "
                        f"{machine_index_base}..{n_machines - 1 + machine_index_base} "
                        f"(job {job_idx + 1} op {op_idx + 1})"
                    )
                if duration < 0:
                    raise FjsParseError(
                        f"negative duration {duration} (job {job_idx + 1} op {op_idx + 1})"
                    )
                if duration > MAX_FJS_DURATION_MINUTES:
                    raise FjsParseError(
                        f"duration {duration} exceeds sanity limit "
                        f"{MAX_FJS_DURATION_MINUTES} (job {job_idx + 1} op {op_idx + 1})"
                    )
                eligible_wc_ids.append(wc_id_by_index[machine_ref - machine_index_base])
                machine_durations[f"M{machine_ref - machine_index_base + 1}"] = duration

            base_duration = min(machine_durations.values())
            horizon_upper_bound_min += max(machine_durations.values())
            operation = Operation(
                order_id=order_id,
                seq_in_order=op_idx + 1,
                state_id=shared_state.id,
                base_duration_min=base_duration,
                eligible_wc_ids=eligible_wc_ids,
                predecessor_op_id=previous_op_id,
                domain_attributes={"fjs_machine_durations": machine_durations},
            )
            operations.append(operation)
            previous_op_id = operation.id

        orders.append(
            Order(
                id=order_id,
                external_ref=f"J{job_idx + 1}",
                # No due dates in the format: due = horizon end (zero tardiness).
                due_date=_HORIZON_START,  # placeholder; fixed below once known
            )
        )

    if stream.remaining() > 0:
        raise FjsParseError(
            f"{stream.remaining()} trailing tokens after the declared {n_jobs} jobs "
            f"(first at token #{stream.index})"
        )

    # Safe horizon: serialized worst-case schedule cannot exceed the sum of
    # per-op max durations. Keep a floor of one day for degenerate instances.
    horizon_minutes = max(horizon_upper_bound_min, 1440)
    # The token cap still admits enough operations that the summed horizon can
    # overflow timedelta's C-int day range; reject before constructing it.
    if horizon_minutes > MAX_FJS_HORIZON_MINUTES:
        raise FjsParseError(
            f"aggregate planning horizon {horizon_minutes} minutes exceeds sanity limit "
            f"{MAX_FJS_HORIZON_MINUTES}"
        )
    horizon_end = _HORIZON_START + timedelta(minutes=horizon_minutes)
    orders = [order.model_copy(update={"due_date": horizon_end}) for order in orders]

    return ScheduleProblem(
        states=[shared_state],
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=[],
        auxiliary_resources=[],
        aux_requirements=[],
        planning_horizon_start=_HORIZON_START,
        planning_horizon_end=horizon_end,
    )


def describe_fjs_mapping() -> dict[str, Any]:
    """Machine-readable statement of the .fjs → SynAPS mapping caveats."""
    return {
        "format": "standard .fjs (Brandimarte / Hurink / DAFJS)",
        "setup_matrix": "empty (format has no SDST)",
        "due_dates": "horizon end (tardiness identically zero; makespan-only scoring)",
        "durations": (
            "base_duration_min = min over listed alternatives; per-pair exact durations "
            "preserved in operation.domain_attributes['fjs_machine_durations']"
        ),
        "comparability_note": (
            "Makespans are NOT directly comparable to per-pair-exact published results "
            "when an instance has heterogeneous alternative durations; report the "
            "mapping alongside any numbers."
        ),
    }


__all__ = ["FjsParseError", "describe_fjs_mapping", "load_fjs_problem"]
