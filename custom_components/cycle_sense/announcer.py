"""Spoken announcements on smart speakers when appliances start or finish."""

from __future__ import annotations

import asyncio
from datetime import datetime, time as dt_time
import logging
import string
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID, STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CHIME_NONE,
    CONF_CHIME,
    DEFAULT_CHIME,
    CONF_MEDIA_PLAYERS,
    CONF_PERSONS,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_TTS,
    DEFAULT_TEXT_FINISHED,
    DEFAULT_VOLUME,
    DOMAIN,
    EVENT_FINISHED,
    EVENT_STARTED,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from . import CycleSenseConfigEntry

_LOGGER = logging.getLogger(__name__)

VARIABLES = ("geraet", "programm", "dauer", "energie", "uhrzeit")
"""Placeholders usable in announcement texts, e.g. "{geraet} ist fertig"."""


class _Keep(dict[str, str]):
    """Leave unknown placeholders untouched instead of failing."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, values: dict[str, str]) -> str:
    """Fill placeholders; tolerate unknown ones and stray braces."""
    try:
        text = string.Formatter().vformat(template, (), _Keep(values))
    except (ValueError, IndexError):
        text = template
    return " ".join(text.split())


def _parse_time(value: str | None) -> dt_time | None:
    if not value:
        return None
    try:
        return dt_time.fromisoformat(value)
    except ValueError:
        return None


def in_quiet_hours(now: dt_time, start: dt_time | None, end: dt_time | None) -> bool:
    """True if ``now`` lies in [start, end), wrapping over midnight."""
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


class Announcer(DataUpdateCoordinator[None]):
    """Listens to Cycle Sense events and speaks them on the chosen speakers."""

    config_entry: CycleSenseConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CycleSenseConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title)
        self.enabled = True
        self.text_finished = DEFAULT_TEXT_FINISHED
        self.text_started = ""
        self.volume = DEFAULT_VOLUME
        self.last_text: str | None = None
        self.last_time: datetime | None = None
        self.last_skipped: str | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._lock = asyncio.Lock()

    @property
    def options(self) -> dict[str, Any]:
        """Data merged with options (options win)."""
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_start(self) -> None:
        """Restore settings and subscribe to appliance events."""
        if data := await self._store.async_load():
            self.enabled = data.get("enabled", True)
            self.text_finished = data.get("text_finished", DEFAULT_TEXT_FINISHED)
            self.text_started = data.get("text_started", "")
            self.volume = data.get("volume", DEFAULT_VOLUME)
        entry = self.config_entry
        entry.async_on_unload(self.hass.bus.async_listen(EVENT_FINISHED, self._on_finished))
        entry.async_on_unload(self.hass.bus.async_listen(EVENT_STARTED, self._on_started))

    # ------------------------------------------------------------ settings

    @callback
    def async_set(self, **changes: Any) -> None:
        """Change a setting from an entity and persist it."""
        for key, value in changes.items():
            setattr(self, key, value)
        self._store.async_delay_save(self._data, 1)
        self.async_update_listeners()

    def _data(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "text_finished": self.text_finished,
            "text_started": self.text_started,
            "volume": self.volume,
        }

    # -------------------------------------------------------------- events

    @callback
    def _on_finished(self, event: Event) -> None:
        if event.data.get("reason") != "quiet":
            return
        self._schedule(self.text_finished, event.data)

    @callback
    def _on_started(self, event: Event) -> None:
        if self.text_started.strip():
            self._schedule(self.text_started, event.data)

    @callback
    def _schedule(self, template: str, data: dict[str, Any]) -> None:
        if data.get("entry_id") == self.config_entry.entry_id:
            return
        text = render(template, self.values(data))
        self.config_entry.async_create_background_task(
            self.hass, self.async_announce(text), f"{DOMAIN}_announce"
        )

    def values(self, data: dict[str, Any]) -> dict[str, str]:
        """Placeholder values for one event."""
        duration = data.get("duration_min")
        energy = data.get("energy_kwh")
        return {
            "geraet": data.get("name") or "",
            "programm": data.get("program") or "",
            "dauer": str(round(duration)) if duration is not None else "",
            "energie": f"{energy:.2f}".replace(".", ",") if energy is not None else "",
            "uhrzeit": dt_util.now().strftime("%H:%M"),
        }

    # ------------------------------------------------------------ speaking

    def _skip_reason(self) -> str | None:
        if not self.enabled:
            return "disabled"
        opts = self.options
        if in_quiet_hours(
            dt_util.now().time(),
            _parse_time(opts.get(CONF_QUIET_START)),
            _parse_time(opts.get(CONF_QUIET_END)),
        ):
            return "quiet_hours"
        persons = opts.get(CONF_PERSONS) or []
        if persons and not any(
            (s := self.hass.states.get(p)) is not None and s.state == STATE_HOME for p in persons
        ):
            return "nobody_home"
        return None

    async def async_announce(self, text: str, *, force: bool = False) -> bool:
        """Speak ``text``; returns False if skipped or nothing could play."""
        if not force and (reason := self._skip_reason()):
            self.last_skipped = reason
            self.async_update_listeners()
            _LOGGER.debug("Announcement skipped (%s): %s", reason, text)
            return False
        opts = self.options
        players = [
            p
            for p in opts.get(CONF_MEDIA_PLAYERS, [])
            if (s := self.hass.states.get(p)) is not None
            and s.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        ]
        tts_entity = opts.get(CONF_TTS)
        if not players or not tts_entity or not text:
            _LOGGER.warning("Announcement not possible: players=%s tts=%s", players, tts_entity)
            return False

        chime = opts.get(CONF_CHIME, DEFAULT_CHIME)
        if chime and chime != CHIME_NONE and self.hass.services.has_service("chime_tts", "say"):
            async with self._lock:
                # Chime TTS merges chime + speech into one file (no gap, one
                # AirPlay start) and handles volume set/restore itself.
                await self.hass.services.async_call(
                    "chime_tts",
                    "say",
                    {
                        ATTR_ENTITY_ID: players,
                        "chime_path": chime,
                        "message": text,
                        "tts_platform": tts_entity,
                        "volume_level": round(self.volume / 100, 2),
                        "cache": True,
                        "join_players": False,
                    },
                    blocking=True,
                )
            self._spoken(text)
            return True

        async with self._lock:
            previous = {
                p: self.hass.states.get(p).attributes.get("volume_level") for p in players
            }
            await self._set_volume(players, self.volume / 100)
            try:
                await self.hass.services.async_call(
                    "tts",
                    "speak",
                    {
                        ATTR_ENTITY_ID: tts_entity,
                        "media_player_entity_id": players,
                        "message": text,
                        "cache": True,
                    },
                    blocking=True,
                )
                # Rough speaking time plus AirPlay start-up before restoring volume.
                await asyncio.sleep(min(30.0, 4.0 + len(text) * 0.08))
            finally:
                for player, level in previous.items():
                    if level is not None:
                        await self._set_volume([player], level)
        self._spoken(text)
        return True

    @callback
    def _spoken(self, text: str) -> None:
        self.last_text = text
        self.last_time = dt_util.now()
        self.last_skipped = None
        self.async_update_listeners()

    async def _set_volume(self, players: list[str], level: float) -> None:
        try:
            await self.hass.services.async_call(
                "media_player",
                "volume_set",
                {ATTR_ENTITY_ID: players, "volume_level": round(level, 2)},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - a speaker without volume control must not block speaking
            _LOGGER.debug("Could not set volume on %s", players, exc_info=True)

    async def async_stop(self) -> None:
        """Persist settings."""
        await self._store.async_save(self._data())
