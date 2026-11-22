"""The first-divergence engine: align a working run against a broken run.

Given two :class:`Timeline`\\s of *semantically the same* program -- one that behaved
(``working``) and one that did not (``broken``) -- this finds the **earliest causally
relevant difference** and suppresses the flood of downstream differences it caused.
That is the difference between "here are 50,000 differences" and "the broken run
could not load its configuration; everything after is fallout".

Alignment is a sequence diff over each event's :meth:`BlackboxEvent.semantic_key`
(``difflib`` style opcodes over Myers alignment). A divergence is one of:

* **result-diff** -- both runs did the same operation, but one failed and the other
  did not (the classic "key present here, NAME NOT FOUND there").
* **working-only** -- the working run did something the broken run never did (the
  broken run *stopped short*).
* **broken-only** -- the broken run did something extra (usually a symptom).

Clocks in two runs are independent; both are assumed to start at 0 at process start,
so the broken run's termination time is used as the cutoff past which "working-only"
events are just the working run outliving the broken one, not root causes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .events import BlackboxEvent, EventType
from .myersdiff import intern_two, myers_opcodes
from .timeline import Timeline


@dataclass
class Divergence:
    kind: str                       # "result-diff" | "working-only" | "broken-only"
    working: BlackboxEvent | None
    broken: BlackboxEvent | None
    key: tuple
    when: float                     # best available time (broken side preferred)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    leads_to_termination: bool = False

    def is_causally_relevant(self, before: float = math.inf) -> bool:
        """Could this be a *root* (not a symptom)? Terminal crashes are excluded --
        they are the symptom we are explaining, not the cause."""
        if self.when > before:
            return False
        if self.kind == "result-diff":
            return bool(self.broken and self.broken.is_failure()
                        and not (self.working and self.working.is_failure()))
        if self.kind == "working-only":
            return True
        if self.kind == "broken-only":
            return bool(self.broken and self.broken.is_failure()
                        and not self.broken.is_terminal())
        return False

    def description(self) -> str:
        if self.kind == "result-diff":
            wr = self.working.result if self.working else "?"
            br = self.broken.result if self.broken else "?"
            obj = (self.broken or self.working).object or (self.broken or self.working).operation
            return f"{obj}: working -> {wr!r}, broken -> {br!r}"
        if self.kind == "working-only":
            return f"working run performed, broken run never did: {self.working.label()}"
        return f"broken run performed, working run never did: {self.broken.label()}"


class DiffEngine:
    # Alignment is Myers O((n+m)*d): near-linear for two runs of the same program (small
    # edit distance d). This caps only the pathological case (wildly dissimilar runs);
    # for real traces, reduce first so the aligned set stays small.
    MAX_EDIT_DISTANCE = 2_000_000

    def __init__(self, working: Timeline, broken: Timeline):
        self.working = working
        self.broken = broken
        self.working.sort()
        self.broken.sort()
        self._divergences: list[Divergence] | None = None

    # -- alignment --------------------------------------------------------------
    def align(self):
        """Opcodes over the two runs via Myers diff on interned integer ids
        (O((n+m)*d), collision-free) -- same ``(tag,i1,i2,j1,j2)`` shape difflib returns."""
        a = (ev.semantic_key() for ev in self.working.events)
        b = (ev.semantic_key() for ev in self.broken.events)
        a_ids, b_ids = intern_two(a, b)
        return myers_opcodes(a_ids, b_ids, max_d=self.MAX_EDIT_DISTANCE)

    def _corroborated(self, tl: Timeline, ev: BlackboxEvent) -> bool:
        key = ev.semantic_key()
        sources = {e.source for e in tl.events if e.semantic_key() == key}
        return len(sources) >= 2

    # -- divergences ------------------------------------------------------------
    def divergences(self) -> list[Divergence]:
        if self._divergences is not None:
            return self._divergences
        A, B = self.working.events, self.broken.events
        out: list[Divergence] = []
        for tag, i1, i2, j1, j2 in self.align():
            if tag == "equal":
                for a, b in zip(A[i1:i2], B[j1:j2]):
                    if a.is_failure() != b.is_failure() or (
                        a.result.strip().lower() != b.result.strip().lower()
                        and (a.is_failure() or b.is_failure())
                    ):
                        out.append(Divergence(
                            kind="result-diff", working=a, broken=b,
                            key=b.semantic_key(),
                            when=b.ts if b.ts is not None else a.ts,
                        ))
            elif tag == "delete":
                for a in A[i1:i2]:
                    out.append(Divergence(
                        kind="working-only", working=a, broken=None,
                        key=a.semantic_key(), when=a.ts if a.ts is not None else 0.0,
                    ))
            elif tag == "insert":
                for b in B[j1:j2]:
                    out.append(Divergence(
                        kind="broken-only", working=None, broken=b,
                        key=b.semantic_key(), when=b.ts if b.ts is not None else 0.0,
                    ))
            elif tag == "replace":
                for a in A[i1:i2]:
                    out.append(Divergence(
                        kind="working-only", working=a, broken=None,
                        key=a.semantic_key(), when=a.ts if a.ts is not None else 0.0,
                    ))
                for b in B[j1:j2]:
                    out.append(Divergence(
                        kind="broken-only", working=None, broken=b,
                        key=b.semantic_key(), when=b.ts if b.ts is not None else 0.0,
                    ))
        out.sort(key=lambda d: (d.when, (d.broken or d.working).seq))
        self._divergences = out
        return out

    # -- the answer -------------------------------------------------------------
    def _broken_terminal_time(self) -> float:
        term = self.broken.terminal_event()
        if term is not None and term.is_terminal() and term.ts is not None:
            return term.ts
        return math.inf

    def first_divergence(self) -> Divergence | None:
        """The earliest causally-relevant difference, scored and evidenced.

        Everything after it is downstream fallout, counted but not reported as a
        separate cause (the brief's "N downstream differences suppressed").
        """
        divs = self.divergences()
        if not divs:
            return None
        cutoff = self._broken_terminal_time()
        roots = [d for d in divs if d.is_causally_relevant(before=cutoff)]
        first = roots[0] if roots else divs[0]

        base = {
            "result-diff": 0.85,
            "working-only": 0.70,
            "broken-only": 0.55,
        }.get(first.kind, 0.5)
        evidence = [f"first divergence is a {first.kind}: {first.description()}"]

        if first.kind == "result-diff" and first.working and first.broken:
            if not first.working.is_failure() and first.broken.is_failure():
                evidence.append("working run succeeded here; broken run failed")
        # Corroboration across independent sensors raises confidence.
        side_tl = self.broken if first.broken else self.working
        side_ev = first.broken or first.working
        if side_ev and self._corroborated(side_tl, side_ev):
            base = min(0.98, base + 0.1)
            evidence.append("corroborated by >=2 independent sensors")
        # Linked to the broken run's death?
        if cutoff != math.inf and first.when <= cutoff:
            first.leads_to_termination = True
            base = min(0.98, base + 0.1)
            evidence.append(f"occurs before the broken run terminates (T+{cutoff:.3f}s)")

        downstream = self.downstream_count(first)
        if downstream:
            evidence.append(f"{downstream} downstream difference(s) follow and are suppressed")
        first.confidence = round(base, 3)
        first.evidence = evidence
        return first

    def downstream_count(self, root: Divergence) -> int:
        """How many divergences come strictly after ``root``."""
        divs = self.divergences()
        rk = (root.when, (root.broken or root.working).seq)
        return sum(1 for d in divs if (d.when, (d.broken or d.working).seq) > rk)

    def owner_breakdown(self, timeline: Timeline | None = None, window: float | None = None):
        """Share of events by owning party (optionally only the last ``window`` s).

        Returns an ordered
        list of ``(Owner, count, fraction)`` descending by count.
        """
        from collections import Counter
        from . import ownership

        tl = timeline or self.broken
        events = tl.events
        if window is not None and events:
            term = tl.terminal_event()
            end = term.ts if term and term.ts is not None else max(e.ts or 0 for e in events)
            events = [e for e in events if (e.ts or 0.0) >= end - window]
        c: Counter = Counter()
        for e in events:
            mod = e.module or (e.object if e.type in (EventType.IMAGE_LOAD, EventType.IMAGE_UNLOAD) else None)
            c[ownership.classify(mod) if mod else ownership.Owner.UNKNOWN] += 1
        total = sum(c.values()) or 1
        return [(owner, n, n / total) for owner, n in c.most_common()]
