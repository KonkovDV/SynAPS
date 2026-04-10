"""Tests for the SynAPS error taxonomy and structured logging."""

from __future__ import annotations

import json
import logging

from synaps.logging import _JsonFormatter, get_logger
from synaps.model import ScheduleResult, SolverErrorCategory, SolverStatus


def test_solver_error_category_has_recovery_hint_for_each_member() -> None:
    for category in SolverErrorCategory:
        hint = category.recovery_hint
        assert isinstance(hint, str)
        assert len(hint) > 5, f"{category} should have a meaningful recovery hint"


def test_solver_error_category_default_is_none() -> None:
    result = ScheduleResult(solver_name="test", status=SolverStatus.OPTIMAL)
    assert result.error_category == SolverErrorCategory.NONE


def test_schedule_result_accepts_error_category() -> None:
    result = ScheduleResult(
        solver_name="test",
        status=SolverStatus.ERROR,
        error_category=SolverErrorCategory.CONSTRUCTIVE_FAILURE,
    )
    assert result.error_category == SolverErrorCategory.CONSTRUCTIVE_FAILURE
    assert "feasible slot" in result.error_category.recovery_hint


def test_json_formatter_produces_valid_json() -> None:
    formatter = _JsonFormatter()
    record = logging.LogRecord(
        name="synaps.test",
        level=logging.INFO,
        pathname="(test)",
        lineno=0,
        msg="test_event",
        args=(),
        exc_info=None,
    )
    record._structured_extra = {"solver": "CPSAT-10", "ops": 42}  # type: ignore[attr-defined]

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["msg"] == "test_event"
    assert parsed["level"] == "info"
    assert parsed["solver"] == "CPSAT-10"
    assert parsed["ops"] == 42


def test_get_logger_returns_structured_logger() -> None:
    log = get_logger("synaps.test_module")
    # Should not raise
    log.info("test_event", key="value")
    log.debug("debug_event")
    log.warning("warn_event", count=5)
    log.error("error_event", detail="something")
