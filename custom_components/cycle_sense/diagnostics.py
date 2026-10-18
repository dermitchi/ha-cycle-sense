"""Diagnostics download for Cycle Sense."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import CycleSenseConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CycleSenseConfigEntry
) -> dict[str, Any]:
    """Return everything needed to reproduce detection issues offline."""
    manager = entry.runtime_data
    match = manager.match
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "config": vars(manager.config),
        "detector": manager.detector.to_dict(),
        "match": None
        if match is None
        else {
            "program": match.profile.name,
            "confidence": match.confidence,
            "distance": match.distance,
            "position": match.position,
            "remaining_s": match.remaining_s,
        },
        "learn_mode": manager.learn_mode,
        "learn_name": manager.learn_name,
        "history": manager.history,
        "profiles": manager.profiles.to_dict(),
    }
