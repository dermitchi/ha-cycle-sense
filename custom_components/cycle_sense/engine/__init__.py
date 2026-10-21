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
from .load import LoadEstimate, estimate as estimate_load, heat_wh, heating_end
from .profiles import (
    SHOW_CONFIDENCE,
    LearnResult,
    Match,
    Matcher,
    Profile,
    ProfileStore,
    Sample,
)

__all__ = [
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
    "dtw_distance",
    "estimate_load",
    "feature",
    "features",
    "heat_wh",
    "heating_end",
]
