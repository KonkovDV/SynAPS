"""Smoke tests for installed SynAPS wheel."""

import importlib

import pytest


def test_package_import() -> None:
    """Verify synaps is importable."""
    synaps = importlib.import_module("synaps")
    assert hasattr(synaps, "__version__")


def test_portfolio_entrypoints() -> None:
    """Verify solve and repair entrypoints are accessible."""
    from synaps import repair_schedule, solve_schedule

    assert callable(solve_schedule)
    assert callable(repair_schedule)


def test_solver_registry_accessible() -> None:
    """Verify solver registry is importable and non-empty."""
    from synaps.solvers.registry import available_solver_configs

    configs = available_solver_configs()
    assert len(configs) > 0


def test_native_accel_optional() -> None:
    """Native accelerator is optional; if present, exports must load."""
    try:
        from synaps.accelerators import greedy_repair_batch_native  # noqa: F401
    except ImportError:
        pytest.skip("synaps_native not installed")
