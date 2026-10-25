"""Seed-reproducible entity identifiers for the synthetic instance generators."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from collections.abc import Callable


def seeded_uuid_factory(seed: int | None) -> Callable[[], UUID]:
    """Return a ``uuid4``-shaped ID source that a seed makes reproducible.

    Audit 2026-10 (A-13): the generators drew ``uuid4()`` IDs, so one seed gave
    a different instance on every call. Solvers break ties by ``str(id)``, so
    the schedule for a "seeded" instance was not reproducible either. The IDs
    come from a DEDICATED stream (a string seed hashes deterministically,
    independent of ``PYTHONHASHSEED``), so the draw sequence of the structural
    RNG (durations, eligibility, setups) is untouched by the fix.
    ``seed=None`` keeps random ``uuid4`` IDs.
    """
    if seed is None:
        return uuid4
    rng = random.Random(f"synaps-ids:{seed}")
    return lambda: UUID(int=rng.getrandbits(128), version=4)
