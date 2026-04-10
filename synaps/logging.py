"""Structured logging for the SynAPS solver portfolio.

Provides a thin JSON-structured wrapper around stdlib ``logging`` so that
solver events, routing decisions, and feasibility results can be consumed
by log aggregation pipelines without adding a third-party dependency.

Usage::

    from synaps.logging import get_logger

    log = get_logger("synaps.portfolio")
    log.info("solve_started", solver_config="CPSAT-30", op_count=120)
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "_structured_extra", None)
        if extra:
            payload.update(extra)
        if record.exc_info and record.exc_info[1] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class _StructuredLogger:
    """Thin wrapper that binds keyword arguments as structured fields."""

    __slots__ = ("_logger",)

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _log(self, level: int, event: str, **kwargs: Any) -> None:
        if not self._logger.isEnabledFor(level):
            return
        record = self._logger.makeRecord(
            self._logger.name,
            level,
            "(structured)",
            0,
            event,
            (),
            None,
        )
        record._structured_extra = kwargs  # type: ignore[attr-defined]
        self._logger.handle(record)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, **kwargs)


_configured = False


def configure_logging(*, level: int = logging.INFO) -> None:
    """Attach the JSON formatter to the ``synaps`` logger hierarchy."""
    global _configured  # noqa: PLW0603
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("synaps")
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True


def get_logger(name: str) -> _StructuredLogger:
    """Return a structured logger bound to *name*."""
    configure_logging()
    return _StructuredLogger(name)


__all__ = ["configure_logging", "get_logger"]
