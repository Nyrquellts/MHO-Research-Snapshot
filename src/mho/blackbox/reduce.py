"""Hierarchical reduction of a streamed event trace: SEE EVERYTHING != KEEP EVERYTHING.

A raw ETW/ProcMon capture can be hundreds of megabytes and millions of events, almost
all of it repetitive *successful* reads. Materialising that into a Timeline (and then
running a sequence diff across it) blows up memory and time. This reducer consumes a
**streamed** event iterator (from ``importers.*.stream_file`` / ``iter_tracerpt_file``)
and keeps a *bounded* working set that still contains everything the diff/why layers
need:

* **keep** high-value events verbatim -- process/thread/image lifecycle, exceptions,
  every failure, IPC/network/registry-writes, log markers;
* **expand raw only around interesting windows** -- the ``tail_window`` events before an
  interesting event and a few after, so the lead-up to a crash survives;
* **collapse** the high-volume repetitive *successes* (file reads/writes/opens, registry
  queries) into counted **signatures** -- one representative event per
  ``(type, operation, object)`` group, carrying the collapsed count.

The result is an ordinary :class:`Timeline`, so ``DiffEngine`` and ``CausalGraph`` run
on it unchanged -- and reach the same causal conclusion, because the exception, the
failed dependency and the divergence-bearing events are all preserved; only the quiet
noise is summarised. The working set is bounded by (high-value events + windows) +
(a fixed-size ring) + (a capped signature table), not by the size of the capture.

Pure standard library. No network.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field

from .events import BlackboxEvent, EventType, normalize_object
from .timeline import Timeline

# Always kept verbatim: the events a causal/diff conclusion is built from.
KEEP_TYPES = frozenset({
    EventType.PROCESS_START, EventType.PROCESS_EXIT, EventType.THREAD_START,
    EventType.THREAD_EXIT, EventType.IMAGE_LOAD, EventType.IMAGE_UNLOAD,
    EventType.EXCEPTION, EventType.DEBUG_PATCH, EventType.TCP_CONNECT,
    EventType.DNS, EventType.IPC, EventType.REG_WRITE, EventType.LOG,
})
# The high-volume classes worth collapsing when they *succeed* (a failure of any of
# these is kept, because is_failure() wins in _high_value()).
COLLAPSE_TYPES = frozenset({
    EventType.FILE_READ, EventType.FILE_WRITE, EventType.FILE_OPEN,
    EventType.REG_QUERY, EventType.REG_OPEN,
})


@dataclass
class ReductionConfig:
    tail_window: int = 32          # raw events kept immediately BEFORE an interesting one
    after_window: int = 8          # raw events kept immediately AFTER an interesting one
    collapse_success: bool = True  # collapse repetitive successful reads into signatures
    max_signatures: int = 20000    # cap distinct signature groups (keeps the table bounded)


@dataclass
class HierarchicalReducer:
    config: ReductionConfig = field(default_factory=ReductionConfig)
    seen: int = 0
    collapsed: int = 0

    def __post_init__(self):
        self._kept: list[BlackboxEvent] = []
        self._ring: deque[BlackboxEvent] = deque(maxlen=self.config.tail_window)
        self._sigs: "OrderedDict[tuple, list]" = OrderedDict()
        self._after = 0

    # -- classification ------------------------------------------------------
    def _high_value(self, ev: BlackboxEvent) -> bool:
        return ev.type in KEEP_TYPES or ev.is_failure() or ev.is_terminal()

    # -- streaming feed ------------------------------------------------------
    def feed(self, ev: BlackboxEvent) -> None:
        self.seen += 1
        if self._high_value(ev):
            self._flush_ring()          # the lead-up window becomes kept
            self._kept.append(ev)
            self._after = self.config.after_window
            return
        if self._after > 0:             # the few events right after an interesting one
            self._kept.append(ev)
            self._after -= 1
            return
        if self.config.collapse_success and ev.type in COLLAPSE_TYPES and not ev.is_failure():
            self._collapse(ev)
            return
        self._ring.append(ev)           # quiet, non-collapsible -> sliding recent window

    def _flush_ring(self) -> None:
        if self._ring:
            self._kept.extend(self._ring)
            self._ring.clear()

    def _collapse(self, ev: BlackboxEvent) -> None:
        key = (ev.type.value, (ev.operation or "").lower(), normalize_object(ev.object))
        sig = self._sigs.get(key)
        if sig is None:
            if len(self._sigs) >= self.config.max_signatures:
                self._ring.append(ev)   # over cap: fall back to the ring (still bounded)
                return
            # [count, first_ts, last_ts, result, source, object, operation, type]
            self._sigs[key] = [1, ev.ts, ev.ts, ev.result, ev.source, ev.object,
                               ev.operation, ev.type]
        else:
            sig[0] += 1
            sig[2] = ev.ts
        self.collapsed += 1

    # -- finalize ------------------------------------------------------------
    def finalize(self, label: str = "reduced", outcome: str = "",
                 base_meta: dict | None = None) -> Timeline:
        self._flush_ring()
        reps: list[BlackboxEvent] = []
        for (count, first, last, result, source, obj, op, etype) in self._sigs.values():
            reps.append(BlackboxEvent(
                type=etype, source=source, ts=first, operation=op, object=obj,
                result=result, detail=f"collapsed {count} repetitive events",
                meta={"collapsed": count, "last_ts": last}))
        events = self._kept + reps
        events.sort(key=lambda e: (e.ts if e.ts is not None else float("inf"), 0))
        meta = dict(base_meta or {})
        meta["reduction"] = {
            "seen": self.seen,
            "kept": len(self._kept),
            "signatures": len(self._sigs),
            "collapsed": self.collapsed,
            "emitted": len(events),
            "ratio": round(len(events) / self.seen, 4) if self.seen else 1.0,
        }
        tl = Timeline(label=label, outcome=outcome, meta=meta)
        for ev in events:
            tl.add(ev)
        tl.sort()
        return tl


def reduce_events(events, config: ReductionConfig | None = None,
                  label: str = "reduced", outcome: str = "",
                  base_meta: dict | None = None) -> Timeline:
    """Reduce any event iterator into a bounded :class:`Timeline`.

    The cyclic garbage collector is paused over the firehose loop -- millions of
    short-lived events would otherwise trigger repeated GC sweeps and CPU stutter -- and
    restored with one clean sweep at the end (blueprint rule 5)."""
    import gc

    r = HierarchicalReducer(config or ReductionConfig())
    gc_was_enabled = gc.isenabled()
    if gc_was_enabled:
        gc.disable()
    try:
        for ev in events:
            r.feed(ev)
    finally:
        if gc_was_enabled:
            gc.enable()
            gc.collect()
    return r.finalize(label=label, outcome=outcome, base_meta=base_meta)


def reduce_capture(path: str, kind: str, config: ReductionConfig | None = None,
                   label: str = "reduced", outcome: str = "") -> Timeline:
    """Stream a capture off disk and reduce it, never holding the whole file.

    ``kind`` is ``procmon-csv`` or ``etw-xml``. Memory stays bounded regardless of the
    capture's size.
    """
    from .importers import procmon, etw

    if kind == "procmon-csv":
        stream = procmon.stream_file(path)
        sensor = "procmon-csv"
    elif kind == "etw-xml":
        stream = etw.iter_tracerpt_file(path)
        sensor = "etw-tracerpt-xml"
    else:
        raise ValueError(f"reduce_capture supports procmon-csv / etw-xml, not {kind!r}")
    return reduce_events(stream, config=config, label=label, outcome=outcome,
                         base_meta={"sensor": sensor, "streamed": True})
