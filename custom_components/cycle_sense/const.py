"""Constants for Cycle Sense."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "cycle_sense"

CONF_POWER_SENSOR: Final = "power_sensor"
CONF_DOOR_SENSOR: Final = "door_sensor"
CONF_APPLIANCE_TYPE: Final = "appliance_type"
CONF_ENTRY_TYPE: Final = "entry_type"
ENTRY_APPLIANCE: Final = "appliance"
ENTRY_ANNOUNCER: Final = "announcer"

# Announcer
CONF_MEDIA_PLAYERS: Final = "media_players"
CONF_TTS: Final = "tts_entity"
CONF_QUIET_START: Final = "quiet_start"
CONF_QUIET_END: Final = "quiet_end"
CONF_PERSONS: Final = "persons"
CONF_CHIME: Final = "chime"
CHIME_NONE: Final = "none"
CHIMES: Final = [CHIME_NONE, "airport", "classical", "doorbell", "bright", "bells", "bells_2", "chord", "chirp", "ding_dong", "glockenspiel", "marimba"]
DEFAULT_CHIME: Final = "airport"
DEFAULT_TEXT_FINISHED: Final = "{geraet} ist fertig."
DEFAULT_TEXT_DRYER_FREE: Final = "Der Trockner ist frei und kann direkt befüllt werden."
DEFAULT_TEXT_REMINDER: Final = "Erinnerung: {geraet} ist seit {seit} fertig und wartet aufs Ausräumen."
CONF_REMINDERS: Final = "reminders"
DEFAULT_REMINDERS: Final = "60, 120"
DEFAULT_VOLUME: Final = 40
DEFAULT_QUIET_START: Final = "22:00:00"
DEFAULT_QUIET_END: Final = "07:00:00"

TYPE_WASHER: Final = "washer"
TYPE_DRYER: Final = "dryer"
TYPE_DISHWASHER: Final = "dishwasher"
TYPE_OTHER: Final = "other"
APPLIANCE_TYPES: Final = [TYPE_WASHER, TYPE_DRYER, TYPE_DISHWASHER, TYPE_OTHER]

# User-tunable detector options (keys match DetectorConfig fields).
OPT_START_POWER: Final = "start_power"
OPT_END_POWER: Final = "end_power"
OPT_END_DELAY: Final = "end_delay_s"
OPT_SPIKE_MAX: Final = "spike_max_s"
OPT_MIN_CYCLE: Final = "min_cycle_s"
OPT_FINISHED_TIMEOUT: Final = "finished_timeout_s"

# Defaults per appliance type, derived from real washer/dryer recordings:
# washers dip to standby for up to ~3.5 min mid-cycle and twitch for ~40 min
# after spinning; dryers pulse ~130 W for <=60 s during anti-crease.
TYPE_DEFAULTS: Final[dict[str, dict[str, float]]] = {
    TYPE_WASHER: {
        OPT_START_POWER: 50, OPT_END_POWER: 8, OPT_END_DELAY: 300,
        OPT_SPIKE_MAX: 150, OPT_MIN_CYCLE: 300, OPT_FINISHED_TIMEOUT: 0,
    },
    TYPE_DRYER: {
        OPT_START_POWER: 50, OPT_END_POWER: 10, OPT_END_DELAY: 240,
        OPT_SPIKE_MAX: 150, OPT_MIN_CYCLE: 300, OPT_FINISHED_TIMEOUT: 0,
    },
    TYPE_DISHWASHER: {
        OPT_START_POWER: 20, OPT_END_POWER: 5, OPT_END_DELAY: 1800,
        OPT_SPIKE_MAX: 120, OPT_MIN_CYCLE: 600, OPT_FINISHED_TIMEOUT: 0,
    },
    TYPE_OTHER: {
        OPT_START_POWER: 30, OPT_END_POWER: 5, OPT_END_DELAY: 300,
        OPT_SPIKE_MAX: 120, OPT_MIN_CYCLE: 300, OPT_FINISHED_TIMEOUT: 0,
    },
}

EVENT_STARTED: Final = f"{DOMAIN}_started"
EVENT_FINISHED: Final = f"{DOMAIN}_finished"
EVENT_ABORTED: Final = f"{DOMAIN}_aborted"
EVENT_CLEARED: Final = f"{DOMAIN}_cleared"
EVENT_LEARNED: Final = f"{DOMAIN}_learned"

TICK_SECONDS: Final = 10
NEAR_END_S: Final = 120
"""Quiet time that ends a cycle once a recognised program is at its end."""
MAX_PAUSE_S: Final = 2700
"""Longest a learned in-program pause may stretch the end delay."""
RESTORE_MAX_GAP_S: Final = 1800
HISTORY_SIZE: Final = 50
STORAGE_VERSION: Final = 1
