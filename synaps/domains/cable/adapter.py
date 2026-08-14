"""Encode length-based cable physics onto the SynAPS kernel.

Duration is metres / line speed written into ``base_duration_min``; the kernel
still does not read ``Order.quantity``. Reel-splitting is a preprocessor
(Zhu et al., Processes 14(5):769, 2026), not a search decision. Setup minutes
are parametric family deltas, not Moskabelmet SMED stopwatch claims.
"""

from __future__ import annotations

import math
from typing import NamedTuple


class CableSku(NamedTuple):
    conductor: str
    insulation: str
    color: str
    section_mm2: int


# Parametric changeover table (minutes / scrap metres / kWh). Same order of
# magnitude as published cable SMED (hours, not minutes) — not a plant dump.
_COLOR_SETUP = (240, 15.0, 20.0)
_SECTION_SETUP = (360, 30.0, 45.0)
_INSULATION_SETUP = (400, 40.0, 80.0)
_CONDUCTOR_SETUP = (120, 20.0, 25.0)

STAGES: tuple[tuple[str, str, float], ...] = (
    ("draw", "drawing", 80.0),
    ("strand", "stranding", 40.0),
    ("extrude", "extrusion", 25.0),
    ("sheath", "sheathing", 20.0),
)


def state_code(sku: CableSku) -> str:
    """Canonical SDST state: conductor-insulation-color-section."""

    return f"{sku.conductor}-{sku.insulation}-{sku.color}-{sku.section_mm2}"


def duration_minutes_from_length(length_m: float, line_speed_m_per_min: float) -> int:
    """Integer minutes for a length at a line speed. Independent of WC speed_factor."""

    speed = line_speed_m_per_min if line_speed_m_per_min > 0 else 1.0
    return max(1, math.ceil(max(0.0, length_m) / speed))


def split_length_into_reels(length_m: float, reel_capacity_m: float) -> list[float]:
    """Pre-split an order length into sub-reels of at most ``reel_capacity_m``.

    Last piece keeps the remainder. Empty / non-positive length yields one
    zero-length placeholder so callers still emit a chain.
    """

    capacity = reel_capacity_m if reel_capacity_m > 0 else 1.0
    remaining = max(0.0, length_m)
    if remaining <= 0:
        return [0.0]
    pieces: list[float] = []
    while remaining > capacity + 1e-9:
        pieces.append(capacity)
        remaining -= capacity
    pieces.append(round(remaining, 3))
    return pieces


def setup_transition(from_sku: CableSku, to_sku: CableSku) -> tuple[int, float, float]:
    """Return ``(setup_minutes, material_loss_m, energy_kwh)`` for a SKU pair."""

    if from_sku == to_sku:
        return 0, 0.0, 0.0
    minutes = 0
    loss = 0.0
    energy = 0.0
    if from_sku.conductor != to_sku.conductor:
        minutes += _CONDUCTOR_SETUP[0]
        loss += _CONDUCTOR_SETUP[1]
        energy += _CONDUCTOR_SETUP[2]
    if from_sku.insulation != to_sku.insulation:
        minutes += _INSULATION_SETUP[0]
        loss += _INSULATION_SETUP[1]
        energy += _INSULATION_SETUP[2]
    if from_sku.section_mm2 != to_sku.section_mm2:
        minutes += _SECTION_SETUP[0]
        loss += _SECTION_SETUP[1]
        energy += _SECTION_SETUP[2]
    if from_sku.color != to_sku.color:
        minutes += _COLOR_SETUP[0]
        loss += _COLOR_SETUP[1]
        energy += _COLOR_SETUP[2]
    return minutes, loss, energy
