"""Loader for the tiny Wave-5 ``*.sdstfjs`` FJSP-SDST slice.

Extends :func:`benchmark.fjs_loader.load_fjs_problem` with trailing per-machine
job×job setup matrices (see ``benchmark/instances/public/sdst/README.md``).
States are one-per-job so SDST maps to SynAPS ``SetupEntry`` cells.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from benchmark.fjs_loader import FjsParseError, load_fjs_problem
from synaps.model import SetupEntry, State


def load_sdst_fjs_problem(path: str | Path):
    """Parse ``*.sdstfjs`` into a ScheduleProblem with a non-empty setup_matrix."""
    path = Path(path)
    tokens = path.read_text(encoding="utf-8").split()
    if len(tokens) < 3:
        raise FjsParseError(f"{path}: empty or truncated SDST-FJS file")
    try:
        n_jobs = int(tokens[0])
        n_machines = int(tokens[1])
    except ValueError as exc:
        raise FjsParseError(f"{path}: header must start with n_jobs n_machines") from exc
    if n_jobs <= 0 or n_machines <= 0:
        raise FjsParseError(f"{path}: non-positive shape {n_jobs}x{n_machines}")

    matrix_tokens = n_machines * n_jobs * n_jobs
    if len(tokens) < matrix_tokens + 3:
        raise FjsParseError(
            f"{path}: need {matrix_tokens} trailing setup ints; got file with {len(tokens)} tokens"
        )
    fjs_tokens = tokens[: len(tokens) - matrix_tokens]
    try:
        matrix_vals = [int(t) for t in tokens[len(tokens) - matrix_tokens :]]
    except ValueError as exc:
        raise FjsParseError(f"{path}: setup matrix must be integers") from exc

    with tempfile.NamedTemporaryFile(
        "w", suffix=".fjs", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(" ".join(fjs_tokens))
        tmp_path = Path(handle.name)
    try:
        problem = load_fjs_problem(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if len(problem.orders) != n_jobs or len(problem.work_centers) != n_machines:
        raise FjsParseError(
            f"{path}: shape mismatch after fjs parse "
            f"(jobs={len(problem.orders)}/{n_jobs}, "
            f"machines={len(problem.work_centers)}/{n_machines})"
        )

    job_states = [State(code=f"J{i + 1}") for i in range(n_jobs)]
    order_index = {order.id: idx for idx, order in enumerate(problem.orders)}
    new_ops = [
        op.model_copy(update={"state_id": job_states[order_index[op.order_id]].id})
        for op in problem.operations
    ]

    setups: list[SetupEntry] = []
    cursor = 0
    for wc in problem.work_centers:
        for from_job in range(n_jobs):
            for to_job in range(n_jobs):
                minutes = matrix_vals[cursor]
                cursor += 1
                if from_job == to_job:
                    continue
                if minutes < 0:
                    import warnings

                    warnings.warn(
                        f"SDST matrix negative setup dropped "
                        f"(wc={wc.code}, from_job={from_job}, to_job={to_job}, minutes={minutes})",
                        UserWarning,
                        stacklevel=2,
                    )
                    continue
                if minutes == 0:
                    continue
                setups.append(
                    SetupEntry(
                        work_center_id=wc.id,
                        from_state_id=job_states[from_job].id,
                        to_state_id=job_states[to_job].id,
                        setup_minutes=int(minutes),
                    )
                )

    return problem.model_copy(
        update={
            "states": job_states,
            "operations": new_ops,
            "setup_matrix": setups,
        }
    )


__all__ = ["load_sdst_fjs_problem"]
