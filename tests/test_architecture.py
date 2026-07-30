"""Phase 0.4 (final brief): architecture tests for singleness and honesty.

Four enforced rules, each answering a defect class the external audits found:

1. No division of ``base_duration_min`` by a speed factor outside
   ``synaps/timegrain.py`` (P0-4: the duration formula lived in 10 places).
   Remaining raw-division sites are a RATCHET list that must only shrink; they
   are scheduled for removal in Phase 3 (ceil canonicalization).
2. No second implementation of a predicate that lives in
   ``synaps/validation.py`` (N4: two metricity implementations, the canonical
   one dead).
3. No public (non-underscore) top-level function in ``synaps/`` without a
   production reference (N4: ``validate_setup_matrix_metricity`` shipped
   uncalled).
4. No function longer than 80 lines outside the RATCHET exception list, which
   must only shrink from PR to PR (Phase 5: a 2600-line ``solve`` cannot be
   unit-tested; that is how M2 survived unnoticed).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SYNAPS_ROOT = Path(__file__).resolve().parent.parent / "synaps"

# --- Rule 1 ratchet: raw base/speed divisions awaiting Phase 3 removal -------
# Format: (posix-relative path, count of allowed raw divisions).
# This list may only SHRINK. Adding an entry is a P0-4 regression.
_RAW_DURATION_DIVISION_RATCHET: dict[str, int] = {
    # ATCS scoring uses fractional processing time for priority, not placement;
    # unify through timegrain in Phase 3.
    "solvers/greedy_dispatch.py": 2,
    # Window sizing estimate; unify in Phase 3.
    "solvers/rhc/_solver.py": 1,
    # DURATION_MISMATCH compares against the raw physical expectation on
    # purpose (tolerance absorbs the grain divergence until Phase 3 ceil);
    # the second hit is the violation message text quoting the formula.
    "solvers/feasibility_checker.py": 2,
    # Synthetic-instance generator sizing heuristic (not a solver).
    "benchmarks/instance_generator.py": 1,
}

_DURATION_DIVISION = re.compile(
    r"base_duration_min\s*/|/\s*speed_factor\b|/\s*wc_speed|/\s*max_speed_factor\b"
)


def _python_files() -> list[Path]:
    return sorted(SYNAPS_ROOT.rglob("*.py"))


def test_duration_division_only_in_timegrain() -> None:
    """Rule 1: the duration grain lives in timegrain.py; raw divisions ratchet down."""
    found: dict[str, int] = {}
    for path in _python_files():
        rel = path.relative_to(SYNAPS_ROOT).as_posix()
        if rel == "timegrain.py":
            continue
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # comments may cite the formula
            if _DURATION_DIVISION.search(stripped):
                count += 1
        if count:
            found[rel] = count
    new_offenders = {
        rel: n
        for rel, n in found.items()
        if n > _RAW_DURATION_DIVISION_RATCHET.get(rel, 0)
    }
    assert not new_offenders, (
        f"new raw base/speed division outside timegrain.py: {new_offenders}; "
        f"call synaps.timegrain.duration_minutes instead"
    )
    gone = {
        rel: allowed
        for rel, allowed in _RAW_DURATION_DIVISION_RATCHET.items()
        if found.get(rel, 0) < allowed
    }
    assert not gone, (
        f"ratchet is stale (sites were cleaned up - tighten the list): {gone}"
    )


def _top_level_function_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def test_validation_predicates_have_single_implementation() -> None:
    """Rule 2: nothing re-implements a predicate from synaps/validation.py."""
    validation_functions = {
        name
        for name in _top_level_function_names(SYNAPS_ROOT / "validation.py")
        if not name.startswith("_")
    }
    offenders: list[str] = []
    for path in _python_files():
        rel = path.relative_to(SYNAPS_ROOT).as_posix()
        if rel == "validation.py":
            continue
        for name in _top_level_function_names(path):
            # A same-named def is an outright duplicate; a `_name`-style local
            # mirror (the N4 pattern: _setup_matrix_is_metric) also counts.
            for canonical in validation_functions:
                if name == canonical or name.lstrip("_") == canonical.lstrip(
                    "_"
                ).replace("is_", "", 1):
                    offenders.append(f"{rel}::{name} duplicates validation.{canonical}")
    assert not offenders, f"duplicate validation predicate(s): {offenders}"


def test_no_dead_public_functions() -> None:
    """Rule 3: a public function in synaps/ must be referenced in production code."""
    texts = {
        p.relative_to(SYNAPS_ROOT).as_posix(): p.read_text(encoding="utf-8")
        for p in _python_files()
    }
    offenders: list[str] = []
    for rel, text in texts.items():
        tree = ast.parse(text)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name.startswith("_"):
                continue
            references = 0
            for other_rel, other_text in texts.items():
                occurrences = other_text.count(node.name)
                if other_rel == rel:
                    occurrences -= 1  # its own def line
                references += max(0, occurrences)
            if references == 0:
                offenders.append(f"{rel}::{node.name}")
    assert not offenders, (
        f"public function(s) with no production caller (dead fix, N4 pattern): "
        f"{offenders}"
    )


# --- Rule 4 ratchet: functions > 80 lines, snapshot 2026-07 (51 entries) -----
# This list may only SHRINK (Phase 5 decomposes them). Adding an entry or
# growing a length is an architecture regression.
_LONG_FUNCTION_RATCHET: dict[str, int] = {
    "solvers/rhc/_solver.py::solve": 2601,
    "solvers/alns_solver.py::_solve_core": 1652,
    "solvers/feasibility_checker.py::check": 443,
    "solvers/lbbd_hd_solver.py::solve": 432,
    "solvers/lbbd_solver.py::solve": 413,
    "solvers/cpsat_solver.py::solve": 368,
    "solvers/greedy_dispatch.py::_solve_core": 362,
    "solvers/router.py::route_solver_config": 318,
    "solvers/lbbd_hd_solver.py::_solve_precedence_aware_master": 297,
    "solvers/alns_solver.py::_try_native_greedy_repair": 268,
    "solvers/incremental_repair.py::solve": 247,
    "solvers/lbbd_solver.py::_solve_master": 220,
    "solvers/alns_solver.py::_try_native_initial_seed": 217,
    "solvers/alns_solver.py::_destroy_critical_path": 202,
    "benchmarks/instance_generator.py::generate_large_instance": 194,
    "solvers/cpsat_solver.py::_add_machine_order_and_adjacency": 193,
    "model.py::validate_cross_references": 178,
    "solvers/lower_bounds.py::compute_relaxed_makespan_lower_bound": 168,
    "solvers/alns_solver.py::_reanchor_against_frozen": 151,
    "solvers/rhc/_window.py::stabilize_temporal_consistency": 149,
    "solvers/pareto_slice_solver.py::solve": 148,
    "solvers/alns_solver.py::_repair_cpsat_outcome": 144,
    "solvers/cpsat_solver.py::_build_weighted_objective": 140,
    "solvers/alns_solver.py::_destroy_due_pressure": 135,
    "cli.py::main": 130,
    "solvers/instance_generator.py::generate_large_instance": 128,
    "solvers/rhc/_window.py::reanchor_inner_assignments": 124,
    "solvers/cpsat_solver.py::_extract_solution_and_objective": 122,
    "accelerators.py::stabilize_temporal_batch": 120,
    "solvers/lbbd_solver.py::_solve_subproblems": 119,
    "solvers/lbbd_solver.py::_build_subproblem": 119,
    "solvers/rhc/_budget.py::scale_alns_inner_budget": 118,
    "cli.py::_build_parser": 114,
    "solvers/_dispatch_support.py::find_earliest_feasible_slot": 113,
    "solvers/lbbd_hd_solver.py::_generate_all_cuts": 113,
    "portfolio.py::solve_schedule": 110,
    "solvers/alns_solver.py::_normalize_initial_operator_weights": 101,
    "solvers/lbbd_hd_solver.py::_solve_subproblems_parallel": 101,
    "contracts.py::_slice_problem_payload": 95,
    "solvers/lbbd_hd_solver.py::_topological_post_assembly": 95,
    "solvers/alns_solver.py::_evaluate_objective_incremental": 94,
    "problem_profile.py::build_problem_profile": 91,
    "solvers/cpsat_solver.py::_virtualize_parallel_work_centers": 91,
    "solvers/cpsat_solver.py::_apply_sat_parameter_overrides": 91,
    "solvers/lbbd_hd_solver.py::_build_subproblem": 90,
    "accelerators.py::evaluate_objective_batch": 87,
    "solvers/lbbd_solver.py::_solve_subproblems_parallel": 85,
    "solvers/rhc/_policy.py::build_solve_kwargs_from_spec": 85,
    "solvers/rhc/_metadata.py::build_inner_window_summary": 84,
    "solvers/rhc/_cross_window.py::compute_window_quality_summary": 82,
}
_MAX_FUNCTION_LINES = 80
_RATCHET_SLACK = 10  # small headroom so a comment edit does not flip CI


def test_function_length_ratchet() -> None:
    """Rule 4: no function beyond 80 lines outside the shrinking exception list."""
    offenders: list[str] = []
    stale: list[str] = []
    seen: dict[str, int] = {}
    for path in _python_files():
        rel = path.relative_to(SYNAPS_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            end = getattr(node, "end_lineno", node.lineno)
            length = end - node.lineno + 1
            if length <= _MAX_FUNCTION_LINES:
                continue
            key = f"{rel}::{node.name}"
            # Same-named nested/sibling defs: keep the longest.
            seen[key] = max(seen.get(key, 0), length)
    for key, length in sorted(seen.items()):
        allowed = _LONG_FUNCTION_RATCHET.get(key)
        if allowed is None:
            offenders.append(f"{key} ({length} lines, new)")
        elif length > allowed + _RATCHET_SLACK:
            offenders.append(f"{key} ({length} lines, ratchet {allowed})")
    for key in _LONG_FUNCTION_RATCHET:
        if key not in seen:
            stale.append(key)
    assert not offenders, (
        "function(s) exceed the 80-line limit beyond the ratchet: "
        + "; ".join(offenders)
    )
    assert not stale, (
        "ratchet is stale (functions were decomposed - remove them from the "
        f"list): {stale}"
    )
