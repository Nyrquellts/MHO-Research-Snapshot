"""A Timeline: an ordered bag of :class:`BlackboxEvent` for one run, plus queries.

A timeline is *one execution* of a target (a launch attempt, a captured session).
It carries a ``label`` ("working" / "broken" / "attempt-6") and an optional
``outcome`` ("connected" / "crashed" / "exited-early") so a launch matrix can group
runs. Merging two sensors' events for the *same* run is just ``extend`` -- provenance
stays on each event's ``source``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .events import BlackboxEvent, EventType, order_key

SCHEMA = "nyr-blackbox-timeline/1"


@dataclass
class Timeline:
    label: str = "run"
    outcome: str = ""            # free text: connected / crashed / exited-early / ...
    events: list[BlackboxEvent] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    # -- building ---------------------------------------------------------------
    def add(self, ev: BlackboxEvent) -> BlackboxEvent:
        """Append one event, assigning it the next ingest ``seq``."""
        ev.seq = len(self.events)
        self.events.append(ev)
        return ev

    def extend(self, events) -> "Timeline":
        """Append many events (e.g. a second sensor's output), re-sequencing."""
        for ev in events:
            self.add(ev)
        return self

    def sort(self) -> "Timeline":
        """Order events by (time, ingest seq). Idempotent; does not renumber seq."""
        self.events.sort(key=order_key)
        return self

    # -- queries ----------------------------------------------------------------
    def filter(
        self,
        type: EventType | None = None,
        types=None,
        pid: int | None = None,
        tid: int | None = None,
        source: str | None = None,
        grep: str | None = None,
        failures_only: bool = False,
    ) -> list[BlackboxEvent]:
        """Return events matching every supplied predicate (AND)."""
        want_types = set()
        if type is not None:
            want_types.add(type)
        if types:
            want_types.update(types)
        needle = grep.lower() if grep else None
        out = []
        for ev in self.events:
            if want_types and ev.type not in want_types:
                continue
            if pid is not None and ev.pid != pid:
                continue
            if tid is not None and ev.tid != tid:
                continue
            if source is not None and ev.source != source:
                continue
            if failures_only and not ev.is_failure():
                continue
            if needle is not None:
                hay = " ".join(
                    str(x) for x in (ev.operation, ev.object, ev.result, ev.detail, ev.module)
                ).lower()
                if needle not in hay:
                    continue
            out.append(ev)
        return out

    def first(self, **kw) -> BlackboxEvent | None:
        got = self.filter(**kw)
        return got[0] if got else None

    def last(self, **kw) -> BlackboxEvent | None:
        got = self.filter(**kw)
        return got[-1] if got else None

    def around(self, ts: float, window: float = 0.5) -> list[BlackboxEvent]:
        """Events within +/- ``window`` seconds of ``ts`` (the brief's +/-500ms view)."""
        return [ev for ev in self.events if abs((ev.ts or 0.0) - ts) <= window]

    def terminal_event(self) -> BlackboxEvent | None:
        """The event that ended the run: the last EXCEPTION/PROCESS_EXIT, else the
        last event overall."""
        term = [ev for ev in self.events if ev.is_terminal()]
        if term:
            return sorted(term, key=order_key)[-1]
        return sorted(self.events, key=order_key)[-1] if self.events else None

    def pids(self) -> list[int]:
        seen = []
        for ev in self.events:
            if ev.pid is not None and ev.pid not in seen:
                seen.append(ev.pid)
        return seen

    def duration(self) -> float:
        if not self.events:
            return 0.0
        ts = [ev.ts for ev in self.events if ev.ts is not None]
        return (max(ts) - min(ts)) if ts else 0.0

    # -- serialisation ----------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "label": self.label,
            "outcome": self.outcome,
            "meta": self.meta,
            "events": [ev.to_dict() for ev in self.events],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Timeline":
        tl = cls(
            label=d.get("label", "run"),
            outcome=d.get("outcome", ""),
            meta=d.get("meta", {}) or {},
        )
        tl.events = [BlackboxEvent.from_dict(e) for e in d.get("events", [])]
        # Trust stored seq if present and contiguous; otherwise renumber.
        for i, ev in enumerate(tl.events):
            if ev.seq is None:
                ev.seq = i
        return tl

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Timeline":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def __len__(self) -> int:
        return len(self.events)
