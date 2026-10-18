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
    "Match",
    "Matcher",
    "Phase",
    "Profile",
    "ProfileStore",
    "Sample",
    "StreamingDTW",
    "dtw_distance",
    "feature",
    "features",
]
