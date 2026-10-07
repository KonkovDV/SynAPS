"""Generalized precedence edges (FS / SS / FF / SF with min and max lags).

``Operation.predecessor_op_id`` stays the in-order FS/0 chain. A
``PrecedenceEdge`` adds an arbitrary temporal relation between any two
operations, including operations of different orders:

    FS: start(dst)  - end(src)   in [min_lag, max_lag]
    SS: start(dst)  - start(src) in [min_lag, max_lag]
    FF: end(dst)    - end(src)   in [min_lag, max_lag]
    SF: end(dst)    - start(src) in [min_lag, max_lag]

Lags are integer minutes on the planning grid; ``min_lag`` may be negative
(lead), ``max_lag`` ``None`` means unbounded. Solvers that do not encode edges
must not claim a schedule for a problem that carries them (see
``BaseSolver.supports_precedence_edges``).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self
from uuid import UUID  # noqa: TC003 - pydantic resolves field annotations at runtime

from pydantic import BaseModel, model_validator

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from synaps.model import Operation

MAX_SCHEDULE_PRECEDENCE_EDGES = 2_000_000


class PrecedenceType(StrEnum):
    FS = "FS"
    SS = "SS"
    FF = "FF"
    SF = "SF"


class PrecedenceEdge(BaseModel):
    """One generalized temporal relation between two operations."""

    src_op_id: UUID
    dst_op_id: UUID
    type: PrecedenceType = PrecedenceType.FS
    min_lag: int = 0
    max_lag: int | None = None

    @model_validator(mode="after")
    def _lag_bounds(self) -> Self:
        if self.max_lag is not None and self.max_lag < self.min_lag:
            raise ValueError("PrecedenceEdge.max_lag must be >= min_lag")
        return self

    @property
    def src_anchor(self) -> str:
        """``start`` or ``end`` of the source operation."""
        return "end" if self.type in (PrecedenceType.FS, PrecedenceType.FF) else "start"

    @property
    def dst_anchor(self) -> str:
        """``start`` or ``end`` of the destination operation."""
        return "start" if self.type in (PrecedenceType.FS, PrecedenceType.SS) else "end"


def edge_delta(
    edge: PrecedenceEdge, *, src: tuple[float, float], dst: tuple[float, float]
) -> float:
    """Return ``anchor(dst) - anchor(src)`` for ``(start, end)`` pairs."""
    src_value = src[1] if edge.src_anchor == "end" else src[0]
    dst_value = dst[1] if edge.dst_anchor == "end" else dst[0]
    return dst_value - src_value


def edge_violation(
    edge: PrecedenceEdge, *, src: tuple[float, float], dst: tuple[float, float]
) -> str | None:
    """Describe the broken bound, or ``None`` when the edge holds."""
    delta = edge_delta(edge, src=src, dst=dst)
    if delta < edge.min_lag:
        return f"{edge.type.value} delta {delta:g} < min_lag {edge.min_lag}"
    if edge.max_lag is not None and delta > edge.max_lag:
        return f"{edge.type.value} delta {delta:g} > max_lag {edge.max_lag}"
    return None


def precedence_edge_issues(
    edges: list[PrecedenceEdge],
    operations: list[Operation],
) -> list[str]:
    """Referential and structural issues; empty means the edge set is admissible.

    The combined graph of chain predecessors and edges must be acyclic. A cycle
    with negative lags can be satisfiable, but the kernel rejects it rather
    than reasoning about positive cycles (adapters own that analysis).
    """
    if not edges:
        return []
    issues: list[str] = []
    op_ids = {operation.id for operation in operations}
    seen: set[tuple[UUID, UUID, PrecedenceType]] = set()
    for edge in edges:
        if edge.src_op_id not in op_ids:
            issues.append(f"precedence edge references unknown src_op_id {edge.src_op_id}")
        if edge.dst_op_id not in op_ids:
            issues.append(f"precedence edge references unknown dst_op_id {edge.dst_op_id}")
        if edge.src_op_id == edge.dst_op_id:
            issues.append(f"precedence edge cannot connect operation {edge.src_op_id} to itself")
        key = (edge.src_op_id, edge.dst_op_id, edge.type)
        if key in seen:
            issues.append(
                f"duplicate precedence edge {edge.type.value} {edge.src_op_id} -> {edge.dst_op_id}"
            )
        seen.add(key)
    if issues:
        return issues
    pairs = [(edge.src_op_id, edge.dst_op_id) for edge in edges]
    pairs.extend(
        (operation.predecessor_op_id, operation.id)
        for operation in operations
        if operation.predecessor_op_id is not None
    )
    cyclic = _cyclic_nodes(op_ids, pairs)
    if cyclic:
        sample = sorted(str(node) for node in cyclic)[:5]
        issues.append(f"precedence edges form a cycle through operations {sample}")
    return issues


def _cyclic_nodes(nodes: set[UUID], pairs: Iterable[tuple[UUID, UUID]]) -> set[UUID]:
    """Kahn's algorithm; returns nodes left with positive in-degree."""
    succ: dict[UUID, list[UUID]] = defaultdict(list)
    indeg = dict.fromkeys(nodes, 0)
    for src, dst in pairs:
        if src not in indeg or dst not in indeg:
            continue
        succ[src].append(dst)
        indeg[dst] += 1
    frontier = [node for node, degree in indeg.items() if degree == 0]
    while frontier:
        node = frontier.pop()
        for nxt in succ.get(node, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                frontier.append(nxt)
    return {node for node, degree in indeg.items() if degree > 0}


def add_precedence_edge_constraints(
    model: Any,
    edges: list[PrecedenceEdge],
    selected_starts: Mapping[Any, Any],
    selected_ends: Mapping[Any, Any],
) -> int:
    """Post CP-SAT linear constraints for every edge; returns the constraint count."""
    posted = 0
    for edge in edges:
        src_var = (selected_ends if edge.src_anchor == "end" else selected_starts)[edge.src_op_id]
        dst_var = (selected_ends if edge.dst_anchor == "end" else selected_starts)[edge.dst_op_id]
        model.add(dst_var - src_var >= edge.min_lag)
        posted += 1
        if edge.max_lag is not None:
            model.add(dst_var - src_var <= edge.max_lag)
            posted += 1
    return posted


@dataclass
class DispatchPrecedence:
    """Ready-set and earliest-start bound for serial dispatch over min lags.

    Max lags are not enforced by a serial generation scheme; the feasibility
    checker is the authority and rejects a dispatch that breaks them.
    """

    incoming: dict[Any, list[PrecedenceEdge]]
    start_offsets: dict[Any, float]
    end_offsets: dict[Any, float]

    @classmethod
    def build(cls, edges: list[PrecedenceEdge]) -> DispatchPrecedence:
        incoming: dict[Any, list[PrecedenceEdge]] = defaultdict(list)
        for edge in edges:
            incoming[edge.dst_op_id].append(edge)
        return cls(incoming=dict(incoming), start_offsets={}, end_offsets={})

    def ready(self, op_id: Any, scheduled: set[Any]) -> bool:
        return all(edge.src_op_id in scheduled for edge in self.incoming.get(op_id, ()))

    def earliest_start(self, op_id: Any, min_duration: float) -> float:
        """Lower bound on the start offset implied by scheduled sources.

        End-anchored relations subtract the SHORTEST eligible duration, which
        over-approximates the bound for any slower machine (safe direction).
        """
        bound = 0.0
        for edge in self.incoming.get(op_id, ()):
            anchors = self.end_offsets if edge.src_anchor == "end" else self.start_offsets
            src_value = anchors.get(edge.src_op_id)
            if src_value is None:
                continue
            candidate = src_value + edge.min_lag
            if edge.dst_anchor == "end":
                candidate -= min_duration
            bound = max(bound, candidate)
        return bound

    def record(self, op_id: Any, start_offset: float, end_offset: float) -> None:
        self.start_offsets[op_id] = start_offset
        self.end_offsets[op_id] = end_offset


def has_max_lags(edges: list[PrecedenceEdge]) -> bool:
    return any(edge.max_lag is not None for edge in edges)


def edge_counts_by_type(edges: list[PrecedenceEdge]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.type.value] = counts.get(edge.type.value, 0) + 1
    return counts


__all__ = [
    "MAX_SCHEDULE_PRECEDENCE_EDGES",
    "DispatchPrecedence",
    "PrecedenceEdge",
    "PrecedenceType",
    "add_precedence_edge_constraints",
    "edge_counts_by_type",
    "edge_delta",
    "edge_violation",
    "has_max_lags",
    "precedence_edge_issues",
]
