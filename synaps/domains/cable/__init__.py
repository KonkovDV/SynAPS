"""Cable domain public surface (encode-first onto MO-FJSP-SDST-ARC)."""

from synaps.domains.cable.adapter import (
    STAGES,
    CableSku,
    duration_minutes_from_length,
    setup_transition,
    split_length_into_reels,
    state_code,
)
from synaps.domains.cable.campaign import apply_campaign_windows
from synaps.domains.cable.instance import generate_cable_instance
from synaps.domains.cable.kpis import assignment_hamming, cable_kpis, peak_wip_drums
from synaps.domains.cable.weights import CABLE_PVC_WEIGHTS

__all__ = [
    "CABLE_PVC_WEIGHTS",
    "STAGES",
    "CableSku",
    "apply_campaign_windows",
    "assignment_hamming",
    "cable_kpis",
    "duration_minutes_from_length",
    "generate_cable_instance",
    "peak_wip_drums",
    "setup_transition",
    "split_length_into_reels",
    "state_code",
]
