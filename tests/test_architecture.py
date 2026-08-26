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
# Cleared by T-26 (F11): ATCS / RHC window sizing / instance generator all
# route through synaps.timegrain.physical_processing_minutes.
_RAW_DURATION_DIVISION_RATCHET: dict[str, int] = {}

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
        rel: n for rel, n in found.items() if n > _RAW_DURATION_DIVISION_RATCHET.get(rel, 0)
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
    assert not gone, f"ratchet is stale (sites were cleaned up - tighten the list): {gone}"


def _top_level_function_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
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
                if name == canonical or name.lstrip("_") == canonical.lstrip("_").replace(
                    "is_", "", 1
                ):
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
        f"public function(s) with no production caller (dead fix, N4 pattern): {offenders}"
    )


# --- Rule 4 ratchet: functions > 80 lines, snapshot 2026-07 (updated Wave 13) --
# This list may only SHRINK except when a verified Red Team fail-open fix
# necessarily grows a hot path (Wave 12/13 frozen algebra). Prefer extract next.
_LONG_FUNCTION_RATCHET: dict[str, int] = {
    "solvers/rhc/_solver.py::solve": 2652,
    "solvers/alns_solver.py::_solve_core": 1558,
    "solvers/feasibility_checker.py::check": 217,
    "solvers/lbbd_hd_solver.py::solve": 433,
    "solvers/lbbd_solver.py::solve": 386,
    "solvers/cpsat_solver.py::solve": 453,
    "solvers/greedy_dispatch.py::_solve_core": 362,
    "solvers/router.py::route_solver_config": 211,
    "solvers/lbbd_hd_solver.py::_solve_precedence_aware_master": 297,
    "solvers/alns_solver.py::_try_native_greedy_repair": 260,
    "solvers/incremental_repair.py::_solve_core": 237,
    "solvers/cpsat_solver.py::_add_machine_order_and_adjacency": 241,
    "solvers/lbbd_solver.py::_solve_master": 176,
    "solvers/alns_solver.py::_try_native_initial_seed": 217,
    "solvers/alns_solver.py::_destroy_critical_path": 202,
    "benchmarks/instance_generator.py::generate_large_instance": 194,
    "model.py::validate_cross_references": 200,
    "solvers/lower_bounds.py::compute_relaxed_makespan_lower_bound": 180,
    "solvers/alns_solver.py::_repair_cpsat_outcome": 173,
    "solvers/alns_solver.py::_reanchor_against_frozen": 160,
    "solvers/rhc/_window.py::stabilize_temporal_consistency": 90,
    "solvers/pareto_slice_solver.py::solve": 148,
    "solvers/alns_solver.py::_destroy_due_pressure": 135,
    "cli.py::main": 130,
    "solvers/instance_generator.py::generate_large_instance": 128,
    "solvers/rhc/_window.py::reanchor_inner_assignments": 124,
    "solvers/cpsat_solver.py::_extract_solution_and_objective": 122,
    "solvers/cpsat_solver.py::_add_aux_resource_cumulative_constraints": 120,
    "accelerators.py::stabilize_temporal_batch": 120,
    "solvers/lbbd_solver.py::_solve_subproblems": 119,
    "solvers/lbbd_solver.py::_build_subproblem": 97,
    "solvers/rhc/_budget.py::scale_alns_inner_budget": 118,
    "solvers/cpsat_solver.py::_build_weighted_objective": 116,
    "cli.py::_build_parser": 114,
    "solvers/_dispatch_support.py::find_earliest_feasible_slot": 126,
    "solvers/lbbd_hd_solver.py::_generate_all_cuts": 113,
    "solvers/incremental_repair.py::_cpsat_fallback": 111,
    "portfolio.py::solve_schedule": 110,
    "solvers/alns_solver.py::_normalize_initial_operator_weights": 101,
    "solvers/lbbd_hd_solver.py::_solve_subproblems_parallel": 101,
    "solvers/alns_solver.py::_evaluate_objective_incremental": 100,
    "solvers/feasibility_checker.py::_build_lane_sequences": 98,
    "contracts.py::_slice_problem_payload": 95,
    "solvers/lbbd_hd_solver.py::_topological_post_assembly": 95,
    "problem_profile.py::build_problem_profile": 91,
    "solvers/cpsat_solver.py::_virtualize_parallel_work_centers": 91,
    "solvers/cpsat_solver.py::_apply_sat_parameter_overrides": 91,
    "solvers/lbbd_hd_solver.py::_build_subproblem": 86,
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
    assert not offenders, "function(s) exceed the 80-line limit beyond the ratchet: " + "; ".join(
        offenders
    )
    assert not stale, (
        f"ratchet is stale (functions were decomposed - remove them from the list): {stale}"
    )


# --- Rule 5 (T-40 / F4 follow-up): direct ObjectiveValues( in solvers --------
# After T-20 the boundary weighted_sum is canonical via evaluate()+scalarize.
# Direct constructions remain for internal search telemetry; this ratchet may
# only SHRINK as call sites migrate to synaps.objective.evaluate.
_OBJECTIVE_VALUES_CTOR_RATCHET: dict[str, int] = {
    "solvers/alns_solver.py": 3,
    "solvers/cpsat_solver.py": 2,
    "solvers/greedy_dispatch.py": 5,
    "solvers/incremental_repair.py": 1,
    "solvers/lbbd_hd_solver.py": 2,
    "solvers/lbbd_solver.py": 1,
    "solvers/rhc/_solver.py": 0,
}

_OBJECTIVE_VALUES_CTOR = re.compile(r"ObjectiveValues\s*\(")


def test_objective_values_ctor_ratchet() -> None:
    """Rule 5: no new direct ObjectiveValues( constructions in solvers."""
    found: dict[str, int] = {}
    for path in _python_files():
        rel = path.relative_to(SYNAPS_ROOT).as_posix()
        if not (rel.startswith("solvers/") or rel == "portfolio.py"):
            continue
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _OBJECTIVE_VALUES_CTOR.search(stripped):
                count += 1
        if count:
            found[rel] = count
    new_offenders = {
        rel: n for rel, n in found.items() if n > _OBJECTIVE_VALUES_CTOR_RATCHET.get(rel, 0)
    }
    assert not new_offenders, (
        f"new ObjectiveValues( constructions outside the ratchet: {new_offenders}; "
        f"prefer synaps.objective.evaluate at the solver boundary (T-20/T-40)"
    )
    stale = {
        rel: allowed
        for rel, allowed in _OBJECTIVE_VALUES_CTOR_RATCHET.items()
        if found.get(rel, 0) < allowed
    }
    assert not stale, f"ObjectiveValues ctor ratchet is stale (shrink the allowed counts): {stale}"


# --- Rule 6 (T-40 / F6): public lower-bound helpers need a validity test -----
_LB_NAME = re.compile(r"(lower_bound|_lb$|bound$)")


def test_public_lower_bound_helpers_have_validity_tests() -> None:
    """Rule 6: every public *lb/*bound helper is referenced from tests/.

    Private helpers (leading underscore) are exempt. Precedent: S3/F6 — a
    bound without a property/validity test is how over-claim cuts shipped.
    See CONTRIBUTING.md «Lower-bound helpers».
    """
    public_lbs: list[tuple[str, str]] = []
    for path in _python_files():
        rel = path.relative_to(SYNAPS_ROOT).as_posix()
        if not rel.startswith("solvers/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name.startswith("_"):
                continue
            if _LB_NAME.search(node.name):
                public_lbs.append((rel, node.name))

    tests_root = Path(__file__).resolve().parent
    corpus = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in tests_root.rglob("test_*.py")
    )
    missing = [f"{rel}::{name}" for rel, name in public_lbs if name not in corpus]
    assert not missing, (
        "public lower-bound helper(s) lack a test reference "
        f"(add a property/validity test): {missing}"
    )
