"""Pure-Python core of Cycle Sense (no Home Assistant imports, unit-testable)."""

from .detector import (
    CycleRecord,
    Detector,
    DetectorConfig,
    DetectorEvent,
    EventType,
    FinishReason,
    Phase,
)
from .dtw import StreamingDTW, dtw_distance, feature, features
from .load import (
    LoadEstimate,
    blend_remaining,
    estimate as estimate_load,
    heat_wh,
    heating_end,
    heating_over,
    predict_remaining,
    tail_bins,
)
from .profiles import (
    CONFIDENT,
    SHOW_CONFIDENCE,
    LearnResult,
    Match,
    Matcher,
    Profile,
    ProfileStore,
    Sample,
)

__all__ = [
    "CONFIDENT",
    "SHOW_CONFIDENCE",
    "CycleRecord",
    "Detector",
    "DetectorConfig",
    "DetectorEvent",
    "EventType",
    "FinishReason",
    "LearnResult",
    "LoadEstimate",
    "Match",
    "Matcher",
    "Phase",
    "Profile",
    "ProfileStore",
    "Sample",
    "StreamingDTW",
    "blend_remaining",
    "dtw_distance",
    "estimate_load",
    "feature",
    "features",
    "heat_wh",
    "heating_end",
    "heating_over",
    "predict_remaining",
    "tail_bins",
]
