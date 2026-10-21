"""Learned programs and live program recognition.

A *profile* is one program of an appliance ("Cotton 40°"). It keeps a few
recorded *samples*; the sample most similar to all others (the medoid) is
the template used for live matching. Using a real recording instead of an
average keeps sharp phase edges intact.

Thresholds were calibrated on real washer/dryer recordings: repeated runs of
the same program have full-trace distances of ~0.08–0.22 and durations
within ~10 %, while different programs differ in distance, length or both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from statistics import median
import time
from typing import Any
import uuid

from .dtw import StreamingDTW, dtw_distance, feature, features

ACCEPT_DISTANCE = 0.25
"""Max full-trace distance for two runs to count as the same program."""
MAX_DURATION_RATIO = 1.15
"""Max length ratio for two runs to count as the same program."""
MAX_SAMPLES = 8
MAX_UNASSIGNED = 30
MIN_MATCH_BINS = 5
"""Bins observed before a live match is reported."""
SOFTMAX_TAU = 0.04
GOOD_DISTANCE = 0.18
BAD_DISTANCE = 0.35
MAX_OVERRUN = 1.35
"""Drop a candidate once the run is this much longer than the program."""
CONFIDENT = 0.6
"""Confidence needed before a match may change the end delay."""
SHOW_CONFIDENCE = 0.4
"""Confidence needed before a match is shown to the user."""
END_CONFIDENT = 0.8
"""Confidence needed to call a still-active run finished at its program end."""
NEAR_END_FRACTION = 0.05
NEAR_END_MIN_ELAPSED = 0.85
"""Fast finish only once the run is at least this long relative to the program."""


@dataclass
class Sample:
    """One recorded run."""

    trace: list[float]
    duration_s: float
    energy_wh: float
    recorded: float = field(default_factory=time.time)
    source: str = "auto"
    load: float | None = None
    """How full the drum was (0..1) as told by the user, for load calibration."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "trace": self.trace,
            "duration_s": self.duration_s,
            "energy_wh": self.energy_wh,
            "recorded": self.recorded,
            "source": self.source,
            "load": self.load,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Sample:
        """Deserialize."""
        return cls(**data)


def same_program(a: Sample, b: Sample) -> float | None:
    """Distance if both runs look like the same program, else None."""
    longer = max(a.duration_s, b.duration_s)
    shorter = max(1.0, min(a.duration_s, b.duration_s))
    if longer / shorter > MAX_DURATION_RATIO:
        return None
    dist = dtw_distance(features(a.trace), features(b.trace))
    return dist if dist <= ACCEPT_DISTANCE else None


def _trim(samples: list[Sample]) -> None:
    """Cap the sample list, dropping automatic recordings before scanned ones."""
    while len(samples) > MAX_SAMPLES:
        auto = [s for s in samples if s.source != "learn"]
        victim = min(auto or samples, key=lambda s: s.recorded)
        samples.remove(victim)


@dataclass
class Profile:
    """A learned program."""

    id: str
    name: str
    samples: list[Sample] = field(default_factory=list)
    auto_named: bool = False
    template: list[float] = field(default_factory=list, repr=False)
    template_duration_s: float = 0.0

    def rebuild(self) -> None:
        """Pick the medoid sample as template."""
        if not self.samples:
            self.template = []
            return
        feats = [features(s.trace) for s in self.samples]
        n = len(feats)
        totals = [0.0] * n
        for i in range(n):
            for j in range(i + 1, n):
                d = dtw_distance(feats[i], feats[j])
                totals[i] += d
                totals[j] += d
        best = min(range(n), key=totals.__getitem__)
        self.template = list(self.samples[best].trace)
        self.template_duration_s = self.samples[best].duration_s

    @property
    def duration_s(self) -> float:
        """Typical duration."""
        return median(s.duration_s for s in self.samples) if self.samples else 0.0

    @property
    def energy_wh(self) -> float:
        """Typical energy."""
        return median(s.energy_wh for s in self.samples) if self.samples else 0.0

    def summary(self) -> dict[str, Any]:
        """Short description for attributes and diagnostics."""
        return {
            "name": self.name,
            "samples": len(self.samples),
            "duration_min": round(self.duration_s / 60),
            "energy_kwh": round(self.energy_wh / 1000, 2),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize (template is derived and stored for fast startup)."""
        return {
            "id": self.id,
            "name": self.name,
            "auto_named": self.auto_named,
            "samples": [s.to_dict() for s in self.samples],
            "template": self.template,
            "template_duration_s": self.template_duration_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        """Deserialize."""
        prof = cls(
            id=data["id"],
            name=data["name"],
            samples=[Sample.from_dict(s) for s in data.get("samples", [])],
            auto_named=data.get("auto_named", False),
            template=data.get("template", []),
            template_duration_s=data.get("template_duration_s", 0.0),
        )
        if not prof.template and prof.samples:
            prof.rebuild()
        return prof


@dataclass
class LearnResult:
    """Outcome of feeding a finished run to the store."""

    profile: str | None
    created: bool = False
    distance: float | None = None


class ProfileStore:
    """All programs of one appliance plus not-yet-grouped runs."""

    def __init__(self) -> None:
        """Initialize empty."""
        self.profiles: list[Profile] = []
        self.unassigned: list[Sample] = []

    def get(self, name: str) -> Profile | None:
        """Find a profile by name (case-insensitive)."""
        key = name.strip().casefold()
        return next((p for p in self.profiles if p.name.casefold() == key), None)

    def find_sample(self, recorded: float) -> Sample | None:
        """The stored run that started at ``recorded``, wherever it is."""
        for sample in [*self.unassigned, *(s for p in self.profiles for s in p.samples)]:
            if abs(sample.recorded - recorded) < 1:
                return sample
        return None

    def names(self) -> list[str]:
        """Profile names."""
        return [p.name for p in self.profiles]

    def add_sample(self, name: str, sample: Sample, *, auto_named: bool = False) -> Profile:
        """Add a run to a (possibly new) profile."""
        prof = self.get(name)
        if prof is None:
            prof = Profile(id=uuid.uuid4().hex, name=name.strip(), auto_named=auto_named)
            self.profiles.append(prof)
        prof.samples.append(sample)
        _trim(prof.samples)
        prof.rebuild()
        return prof

    def remove_recording(self, recorded: float) -> None:
        """Forget a run wherever it is stored (used before re-assigning it)."""
        # A run is identified by its exact start timestamp.
        self.unassigned = [s for s in self.unassigned if s.recorded != recorded]
        for prof in list(self.profiles):
            kept = [s for s in prof.samples if s.recorded != recorded]
            if len(kept) == len(prof.samples):
                continue
            prof.samples = kept
            if kept:
                prof.rebuild()
            else:
                self.profiles.remove(prof)

    def rename(self, old: str, new: str) -> bool:
        """Rename a profile; merges into an existing one with the new name."""
        prof = self.get(old)
        if prof is None or not new.strip():
            return False
        target = self.get(new)
        if target is not None and target is not prof:
            target.samples.extend(prof.samples)
            _trim(target.samples)
            target.rebuild()
            self.profiles.remove(prof)
            return True
        prof.name = new.strip()
        prof.auto_named = False
        return True

    def delete(self, name: str) -> bool:
        """Delete a profile."""
        prof = self.get(name)
        if prof is None:
            return False
        self.profiles.remove(prof)
        return True

    def classify(self, sample: Sample) -> tuple[Profile, float] | None:
        """Best matching profile for a complete run."""
        best: tuple[Profile, float] | None = None
        for prof in self.profiles:
            for ref in prof.samples:
                dist = same_program(sample, ref)
                if dist is not None and (best is None or dist < best[1]):
                    best = (prof, dist)
        return best

    def next_auto_name(self, fmt: str) -> str:
        """First free 'Program N' name."""
        n = 1
        while self.get(fmt.format(n=n)) is not None:
            n += 1
        return fmt.format(n=n)

    def learn(
        self,
        sample: Sample,
        *,
        name: str | None = None,
        auto_improve: bool = True,
        auto_create: bool = True,
        auto_name_fmt: str = "Program {n}",
    ) -> LearnResult:
        """Store a finished run: explicitly, by match, or by clustering."""
        if name:
            self.remove_recording(sample.recorded)
            prof = self.add_sample(name, sample)
            return LearnResult(prof.name, created=len(prof.samples) == 1)

        if (hit := self.classify(sample)) is not None:
            prof, dist = hit
            if auto_improve:
                self.add_sample(prof.name, sample)
            return LearnResult(prof.name, distance=dist)

        if auto_create:
            group = [u for u in self.unassigned if same_program(sample, u) is not None]
            if group:
                for u in group:
                    self.unassigned.remove(u)
                new_name = self.next_auto_name(auto_name_fmt)
                for s in [*group, sample]:
                    self.add_sample(new_name, s, auto_named=True)
                return LearnResult(new_name, created=True)

        self.unassigned.append(sample)
        del self.unassigned[:-MAX_UNASSIGNED]
        return LearnResult(None)

    def clear_unassigned(self) -> int:
        """Forget all runs not belonging to a program; returns how many."""
        count = len(self.unassigned)
        self.unassigned = []
        return count

    def to_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "profiles": [p.to_dict() for p in self.profiles],
            "unassigned": [s.to_dict() for s in self.unassigned],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ProfileStore:
        """Deserialize."""
        store = cls()
        if data:
            store.profiles = [Profile.from_dict(p) for p in data.get("profiles", [])]
            store.unassigned = [Sample.from_dict(s) for s in data.get("unassigned", [])]
        return store


@dataclass
class Match:
    """Live recognition result."""

    profile: Profile
    confidence: float
    distance: float
    position: int
    remaining_s: float
    progress: float


class Matcher:
    """Compares the running cycle with all profiles, bin by bin."""

    def __init__(self, store: ProfileStore, bin_s: int, end_power: float) -> None:
        """Initialize."""
        self.store = store
        self.bin_s = bin_s
        self.quiet_power = max(end_power * 3, 15.0)
        self._dtw: dict[str, tuple[Profile, StreamingDTW]] = {}
        self.n = 0
        self.pinned: str | None = None

    def reset(self) -> None:
        """Start matching a new cycle against the current profiles."""
        self._dtw = {
            p.id: (p, StreamingDTW(features(p.template)))
            for p in self.store.profiles
            if p.template
        }
        self.n = 0

    def push(self, power: float) -> None:
        """Feed one completed bin of the running cycle."""
        x = feature(power)
        for _, dtw in self._dtw.values():
            dtw.push(x)
        self.n += 1

    def _scored(self) -> list[tuple[Profile, StreamingDTW, float]]:
        out = []
        for prof, dtw in self._dtw.values():
            if dtw.m and self.n > dtw.m * MAX_OVERRUN + 3:
                continue
            out.append((prof, dtw, dtw.distance))
        return out

    def candidates(self) -> list[tuple[Profile, StreamingDTW, float]]:
        """(profile, dtw, probability) sorted best first."""
        if self.n < MIN_MATCH_BINS:
            return []
        scored = self._scored()
        if not scored:
            return []
        best_d = min(d for _, _, d in scored)
        weights = [math.exp(-(d - best_d) / SOFTMAX_TAU) for _, _, d in scored]
        total = sum(weights)
        out = []
        for (prof, dtw, d), w in zip(scored, weights, strict=True):
            # Relative likelihood among programs, scaled by how well the
            # program fits in absolute terms (a run unlike every learned
            # program must not look like a confident match).
            fit = min(1.0, max(0.0, (BAD_DISTANCE - d) / (BAD_DISTANCE - GOOD_DISTANCE)))
            out.append((prof, dtw, w / total * fit))
        out.sort(key=lambda c: c[2], reverse=True)
        return out

    def best(self) -> Match | None:
        """The most likely program, if any."""
        if self.pinned is not None:
            for prof, dtw in self._dtw.values():
                if prof.name == self.pinned:
                    return self._match(prof, dtw, 1.0)
        cands = self.candidates()
        if not cands:
            return None
        prof, dtw, prob = cands[0]
        return self._match(prof, dtw, prob)

    def _match(self, prof: Profile, dtw: StreamingDTW, conf: float) -> Match:
        m = max(1, dtw.m)
        pos = min(dtw.position, m - 1) if self.n else 0
        remaining = max(0, m - 1 - pos) * self.bin_s
        return Match(
            profile=prof,
            confidence=conf,
            distance=dtw.distance,
            position=pos,
            remaining_s=remaining,
            progress=min(1.0, (pos + 1) / m),
        )

    def program_end_reached(self) -> bool:
        """True once a confidently recognised program has run its full length.

        Some appliances keep moving after the program (anti-crease drum turns
        of 100–350 W for minutes). That looks like activity, so the quiet
        rule alone would report the end far too late.
        """
        if self.pinned is not None:
            return False
        match = self.best()
        if match is None or match.confidence < END_CONFIDENT:
            return False
        m = len(match.profile.template)
        # Only right at the learned end: a run that is already longer is
        # some other program that merely starts the same way.
        return (
            m <= self.n <= m + max(3, int(m * NEAR_END_FRACTION))
            and match.position >= m - 2
            and match.distance <= ACCEPT_DISTANCE
        )

    def end_delay(self, default_s: float, near_end_s: float, max_pause_s: float) -> float:
        """Quiet time to wait before calling the cycle finished.

        Near the end of a confidently recognised program a short wait is
        enough. If the program has a long pause at this point (soaking,
        dishwasher drying) the wait is stretched to cover it.
        """
        match = self.best()
        if match is None or match.confidence < CONFIDENT:
            return default_s
        tmpl = match.profile.template
        active = [k for k, p in enumerate(tmpl) if p > self.quiet_power]
        active_end = active[-1] if active else len(tmpl) - 1
        near = max(2, int(len(tmpl) * NEAR_END_FRACTION))
        if (
            active_end - match.position <= near
            and NEAR_END_MIN_ELAPSED * len(tmpl)
            <= self.n
            <= len(tmpl) + max(3, int(len(tmpl) * NEAR_END_FRACTION))
        ):
            return min(default_s, near_end_s)
        pause = 0
        for p in tmpl[match.position + 1 :]:
            if p > self.quiet_power:
                break
            pause += 1
        pause_s = pause * self.bin_s
        if pause_s > default_s * 0.6:
            return min(max_pause_s, max(default_s, pause_s * 1.5 + 120))
        return default_s
