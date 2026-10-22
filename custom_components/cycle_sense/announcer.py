"""Spoken announcements on smart speakers when appliances start or finish."""

from __future__ import annotations

import asyncio
from datetime import datetime, time as dt_time
import logging
import string
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_HOME,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APPLIANCE_TYPE,
    CONF_REMINDERS,
    DEFAULT_TEXT_DRYER_FREE,
    TYPE_DRYER,
    TYPE_WASHER,
    DEFAULT_REMINDERS,
    DEFAULT_TEXT_REMINDER,
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

VARIABLES = ("geraet", "programm", "dauer", "energie", "uhrzeit", "seit")
"""Placeholders usable in announcement texts, e.g. "{geraet} ist fertig"."""

# How much louder than the music an announcement on a playing speaker is.
MUSIC_BOOST = 0.3
# Pause between stopping the music and starting the announcement (s).
AIRPLAY_RELEASE_S = 0.5


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


def join_sentences(first: str, second: str) -> str:
    """Append a sentence, adding a full stop to the first one if missing."""
    first, second = first.strip(), second.strip()
    if not first or not second:
        return first or second
    if first[-1] not in ".!?":
        first += "."
    return f"{first} {second}"


def _duration_text(minutes: int) -> str:
    """German duration for speech, e.g. 60 -> "einer Stunde", 90 -> "90 Minuten"."""
    if minutes % 60:
        return f"{minutes} Minuten"
    hours = minutes // 60
    return "einer Stunde" if hours == 1 else f"{hours} Stunden"


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
        self.texts_finished: dict[str, str] = {}
        self.text_started = ""
        self.text_reminder = DEFAULT_TEXT_REMINDER
        self.text_dryer_free = DEFAULT_TEXT_DRYER_FREE
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
            self.texts_finished = data.get("texts_finished", {})
            self.text_started = data.get("text_started", "")
            self.text_reminder = data.get("text_reminder", DEFAULT_TEXT_REMINDER)
            self.text_dryer_free = data.get("text_dryer_free", DEFAULT_TEXT_DRYER_FREE)
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
            "texts_finished": self.texts_finished,
            "text_started": self.text_started,
            "text_reminder": self.text_reminder,
            "text_dryer_free": self.text_dryer_free,
            "volume": self.volume,
        }

    # -------------------------------------------------------------- events

    @callback
    def _on_finished(self, event: Event) -> None:
        if event.data.get("reason") not in ("quiet", "program_end"):
            return
        entry_id = event.data.get("entry_id")
        text = self.finished_text(entry_id)
        if self.text_dryer_free.strip() and self.dryer_free_after(entry_id):
            text = join_sentences(text, self.text_dryer_free)
        self._schedule(text, event.data)
        self._plan_reminders(dict(event.data))

    def dryer_free_after(self, appliance_entry_id: str | None) -> bool:
        """True if a washer finished and every dryer is free (not running, not waiting)."""
        entry = self.hass.config_entries.async_get_entry(appliance_entry_id or "")
        if entry is None or entry.data.get(CONF_APPLIANCE_TYPE) != TYPE_WASHER:
            return False
        dryers = [
            getattr(e, "runtime_data", None)
            for e in self.hass.config_entries.async_entries(DOMAIN)
            if e.data.get(CONF_APPLIANCE_TYPE) == TYPE_DRYER
        ]
        detectors = [getattr(m, "detector", None) for m in dryers]
        return bool(detectors) and all(
            det is not None and det.available and det.phase == "off" for det in detectors
        )

    def reminder_minutes(self) -> list[int]:
        """Configured reminder delays in minutes, e.g. "60, 120"."""
        raw = str(self.options.get(CONF_REMINDERS, DEFAULT_REMINDERS))
        return sorted({int(p) for p in raw.replace(";", ",").split(",") if p.strip().isdigit() and int(p) > 0})

    @callback
    def _plan_reminders(self, data: dict[str, Any]) -> None:
        """Remind while the appliance still waits to be emptied."""
        entry = self.hass.config_entries.async_get_entry(data.get("entry_id") or "")
        manager = getattr(entry, "runtime_data", None) if entry else None
        since = getattr(getattr(manager, "detector", None), "finished_since", None)
        if since is None:
            return
        for minutes in self.reminder_minutes():

            @callback
            def _fire(_now: Any, minutes: int = minutes) -> None:
                det = getattr(manager, "detector", None)
                if det is None or det.phase != "finished" or det.finished_since != since:
                    return  # emptied or a new cycle in between
                values = data | {"seit": _duration_text(minutes)}
                self._schedule(self.text_reminder, values)

            self.config_entry.async_on_unload(async_call_later(self.hass, minutes * 60, _fire))

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

    def finished_text(self, appliance_entry_id: str | None) -> str:
        """Per-appliance finished text, falling back to the general one."""
        return self.texts_finished.get(appliance_entry_id or "") or self.text_finished

    @callback
    def async_set_finished_text(self, appliance_entry_id: str, text: str) -> None:
        """Set the finished text of one appliance."""
        self.texts_finished = {**self.texts_finished, appliance_entry_id: text}
        self._store.async_delay_save(self._data, 1)
        self.async_update_listeners()

    def values(self, data: dict[str, Any]) -> dict[str, str]:
        """Placeholder values for one event."""
        duration = data.get("duration_min")
        energy = data.get("energy_kwh")
        return {
            "seit": data.get("seit", ""),
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

        # A speaker that is already playing is stopped (an AirPlay stream
        # would block the announcement) and speaks a little louder than its
        # music; an automation can restart the music when the
        # last-announcement sensor updates.
        playing = [p for p in players if self.hass.states.get(p).state == STATE_PLAYING]
        quiet = [p for p in players if p not in playing]
        music_volume = {
            p: self.hass.states.get(p).attributes.get("volume_level") for p in playing
        }

        async def stop_music() -> None:
            if not playing:
                return
            try:
                await self.hass.services.async_call(
                    "media_player", "media_stop", {ATTR_ENTITY_ID: playing}, blocking=True
                )
            except Exception:  # noqa: BLE001 - speaking matters more than stopping
                _LOGGER.debug("Could not stop %s", playing, exc_info=True)

        def louder(player: str) -> float:
            level = music_volume.get(player)
            if level is None:
                return round(self.volume / 100, 2)
            return round(min(1.0, level + MUSIC_BOOST), 2)

        chime = opts.get(CONF_CHIME, DEFAULT_CHIME)
        if chime and chime != CHIME_NONE and self.hass.services.has_service("chime_tts", "say"):
            chime_data = {
                "chime_path": chime,
                # Short breath between chime and voice (ms).
                "offset": 400,
                "message": text,
                "tts_platform": tts_entity,
                "cache": True,
            }

            async def say(targets: list[str], volume: float) -> None:
                # Chime TTS merges chime + speech into one file (no gap, one
                # AirPlay start) and handles volume set/restore itself.
                await self.hass.services.async_call(
                    "chime_tts",
                    "say",
                    chime_data
                    | {ATTR_ENTITY_ID: targets, "volume_level": volume, "join_players": False},
                    blocking=True,
                )

            async with self._lock:
                if playing:
                    await stop_music()
                    # Let the speaker release its AirPlay session, otherwise
                    # the announcement stream fails to start.
                    await asyncio.sleep(AIRPLAY_RELEASE_S)
                calls = [say([p], louder(p)) for p in playing]
                if quiet:
                    calls.append(say(quiet, round(self.volume / 100, 2)))
                await asyncio.gather(*calls)
            self._spoken(text)
            return True

        await stop_music()
        async with self._lock:
            previous = {
                p: self.hass.states.get(p).attributes.get("volume_level") for p in quiet
            }
            await self._set_volume(quiet, self.volume / 100)
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
        if not players:
            return
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
