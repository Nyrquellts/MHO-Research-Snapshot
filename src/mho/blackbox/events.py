"""The evidence ontology: one normalised event every sensor is reduced to.

A :class:`BlackboxEvent` is the atom of Blackbox. Whatever the source -- a ProcMon
row, a client-log marker, an error report -- it becomes one of
these, so the comparison / causal / report layers never need to know where an event
came from (only that it *did*, recorded in ``source`` for provenance).

Everything here is pure data + pure functions: no I/O, no side effects, stdlib only.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, asdict
from enum import Enum


class EventType(str, Enum):
    """The kinds of observable event Blackbox reasons over.

    A ``str`` enum so a value serialises to its own name in JSON with no custom
    encoder. New sensors map their native operations onto these; if nothing fits,
    :data:`EventType.LOG` (a semantic marker) or :data:`EventType.UNKNOWN` is used.
    """

    PROCESS_START = "PROCESS_START"
    PROCESS_EXIT = "PROCESS_EXIT"
    THREAD_START = "THREAD_START"
    THREAD_EXIT = "THREAD_EXIT"
    IMAGE_LOAD = "IMAGE_LOAD"
    IMAGE_UNLOAD = "IMAGE_UNLOAD"
    FILE_OPEN = "FILE_OPEN"
    FILE_READ = "FILE_READ"
    FILE_WRITE = "FILE_WRITE"
    REG_OPEN = "REG_OPEN"
    REG_QUERY = "REG_QUERY"
    REG_WRITE = "REG_WRITE"
    TCP_CONNECT = "TCP_CONNECT"
    DNS = "DNS"
    IPC = "IPC"                 # named pipe / mailslot / shared memory
    EXCEPTION = "EXCEPTION"     # a fault (access violation, etc.)
    DEBUG_PATCH = "DEBUG_PATCH"  # a recorded change marker
    LOG = "LOG"                 # a semantic marker recovered from a log line
    UNKNOWN = "UNKNOWN"


# Result tokens that mean "this operation succeeded" -- everything else that looks
# like a status is treated as a potential failure by :meth:`BlackboxEvent.is_failure`.
_SUCCESS_RESULTS = {
    "", "success", "0", "0x0", "ok", "s_ok", "status_success", "reparse",
    "true", "done", "complete",
}
# Substrings that, in a result string, mark a genuine failure.
_FAILURE_MARKERS = (
    "not found", "no such", "access denied", "denied", "fail", "error",
    "timeout", "timed out", "refused", "unreachable", "invalid", "abort",
    "crash", "exception", "violation", "cannot", "missing", "rejected",
    "disconnect", "closed", "0xc0000", "0x8007", "0x80004",
)

_FRAME_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+?)\s*\+\s*0x([0-9A-Fa-f]+)\s*$")
_ADDR_RE = re.compile(r"0x[0-9A-Fa-f]+")
_TRAILING_ID_RE = re.compile(r"\+\d{2,}\b")
_USERPROFILE_RE = re.compile(r"(?i)([a-z]:/users/)[^/]+/")


def parse_frame(frame: str) -> tuple[str | None, int | None]:
    """Split a stack frame like ``"SampleEngine.dll+0x120"`` into ``(module, rva)``.

    Returns ``(None, None)`` for anything that is not ``module+0xHEX`` (e.g. a bare
    symbol or a Windows-resolved name), so callers can keep the raw string.
    """
    m = _FRAME_RE.match(frame or "")
    if not m:
        return None, None
    return m.group(1), int(m.group(2), 16)


def normalize_object(obj: str) -> str:
    """Canonicalise an event's target so the same thing aligns across two runs.

    Lower-cases, forward-slashes paths, masks volatile bits that differ run to run
    but mean the same thing -- concrete addresses (``0x0010035e``), trailing decimal
    ids appended with ``+`` (``SAMPLE_EVENT_BUFFER+12345``), and the user-profile
    segment of a path -- so a semantic diff is not swamped by noise. The *raw*
    ``object`` is always kept on the event for display; this is only the match key.
    """
    if not obj:
        return ""
    s = obj.strip().replace("\\", "/").lower()
    s = _ADDR_RE.sub("0x#", s)
    s = _TRAILING_ID_RE.sub("+#", s)
    s = _USERPROFILE_RE.sub(r"\1#/", s)
    return s


@dataclass(slots=True)
class BlackboxEvent:
    """One observed event, normalised from any sensor.

    ``slots=True`` cuts the per-object memory tax (~50 B vs ~300 B of instance dict)
    and drops GC pressure -- it matters when a capture is millions of events.

    Attributes:
        seq: monotonic ingest index; the stable tiebreaker when timestamps tie or
            are synthetic. Assigned by the :class:`~mho.blackbox.timeline.Timeline`.
        ts: relative time in seconds from the start of the run. Importers that lack
            real timestamps use the line index, so ordering is always defined.
        source: provenance -- which sensor produced this (``procmon``, ``dbglog``,
            ``clientlog``, ``synthetic`` ...). Two events with the same
            :meth:`semantic_key` but different sources *corroborate* each other.
        pid / tid: process / thread the event belongs to (``None`` if unknown).
        type: the :class:`EventType`.
        operation: the native operation name (``RegQueryValue``, ``TerminateProcess``,
            ``READ_AV`` ...), kept verbatim for display.
        object: the target (registry key, file path, module, ``host:port``, pipe).
        result: the native result/status string (``SUCCESS``, ``NAME NOT FOUND``,
            ``0xC0000005`` ...).
        detail: freeform extra text.
        module: the owning / faulting module, when known (e.g. an exception's module).
        rva: offset within ``module`` for a fault or frame.
        stack: call-stack frames, innermost last, as raw strings.
        meta: any extra structured fields a sensor wants to carry.
    """

    type: EventType = EventType.UNKNOWN
    source: str = "synthetic"
    ts: float = 0.0
    seq: int = 0
    pid: int | None = None
    tid: int | None = None
    operation: str = ""
    object: str = ""
    result: str = ""
    detail: str = ""
    module: str | None = None
    rva: int | None = None
    stack: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    # -- classification ---------------------------------------------------------
    def is_failure(self) -> bool:
        """Best-effort: did this event represent something going wrong?

        An :data:`EventType.EXCEPTION` is always a failure. Otherwise the ``result``
        string is checked against a small allowlist of success tokens and a list of
        failure markers. This is a *heuristic sensor reading*, not ground truth --
        the causal layer corroborates it before drawing conclusions.
        """
        if self.type == EventType.EXCEPTION:
            return True
        r = (self.result or "").strip().lower()
        if r in _SUCCESS_RESULTS:
            return False
        if any(marker in r for marker in _FAILURE_MARKERS):
            return True
        # A hex status with the top NTSTATUS bits set (0xC.. error, 0x8.. warning).
        if r.startswith("0x") and len(r) >= 3 and r[2] in "89abcdef":
            return True
        return False

    def is_terminal(self) -> bool:
        """True for events that end a process (exit or a fatal exception)."""
        return self.type in (EventType.PROCESS_EXIT, EventType.EXCEPTION) or (
            self.operation or ""
        ).lower() in ("terminateprocess", "exitprocess", "process exit")

    # -- alignment key ----------------------------------------------------------
    def semantic_key(self) -> tuple:
        """The identity used to align this event against another run's events.

        Type-aware so the *same thing* matches even when volatile detail differs:

        * ``EXCEPTION`` -> ``(EXCEPTION, module, rva)`` so a crash at the same site
          matches regardless of the garbage address it faulted on.
        * ``IMAGE_LOAD`` / ``IMAGE_UNLOAD`` -> ``(type, module-basename)``.
        * everything else -> ``(type, operation, normalized object)``.
        """
        if self.type == EventType.EXCEPTION:
            mod = (self.module or "").lower()
            return (self.type.value, mod, self.rva)
        if self.type in (EventType.IMAGE_LOAD, EventType.IMAGE_UNLOAD):
            base = normalize_object(self.module or self.object)
            base = base.rsplit("/", 1)[-1]
            return (self.type.value, base)
        return (self.type.value, (self.operation or "").lower(), normalize_object(self.object))

    # -- display ----------------------------------------------------------------
    def label(self) -> str:
        """A one-line human label for reports."""
        who = self.module or self.object or self.operation or self.type.value
        if self.type == EventType.EXCEPTION and self.module and self.rva is not None:
            who = f"{self.module}+0x{self.rva:X}"
        parts = [self.type.value]
        if self.operation:
            parts.append(self.operation)
        if who and who not in parts:
            parts.append(who)
        if self.result:
            parts.append(f"-> {self.result}")
        return " ".join(parts)

    # -- serialisation ----------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BlackboxEvent":
        d = dict(d)
        t = d.get("type", "UNKNOWN")
        d["type"] = EventType(t) if not isinstance(t, EventType) else t
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def order_key(ev: BlackboxEvent) -> tuple:
    """Sort key for a timeline: by time, then ingest order; NaN/inf-safe."""
    ts = ev.ts
    if ts is None or (isinstance(ts, float) and math.isnan(ts)):
        ts = math.inf
    return (ts, ev.seq)
