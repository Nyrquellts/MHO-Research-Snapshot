"""The ``why`` engine: walk the causal graph back from termination to a cause.

Given one run (a :class:`Timeline`), :meth:`CausalGraph.why_exit` reconstructs the
an evidence chain from process exit -> the fatal fault -> the call
stack that reached it (each frame attributed to its owner) -> the thread it ran on ->
the nearest preceding *failed dependency*. When a working run is also available, its
:class:`DiffEngine` first-divergence is appended as the ultimate root, tying the
comparison and causal layers together.

The proximate chain (which module faulted, on which thread, reached via which frames)
is *observed fact* and gets high confidence. The ultimate root (why the data feeding
that site was invalid) is inference: it is asserted only from a diff against a working
run, and otherwise left explicitly UNKNOWN rather than guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ownership
from .events import BlackboxEvent, EventType, parse_frame
from .ownership import Owner
from .timeline import Timeline


@dataclass
class CausalStep:
    relation: str                     # exit | fault | called-from | thread | proximate | root | unknown
    text: str
    owner: Owner | None = None
    event: BlackboxEvent | None = None
    observed: bool = True             # observed fact vs inferred


@dataclass
class CausalChain:
    steps: list[CausalStep] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def root(self) -> CausalStep | None:
        return self.steps[-1] if self.steps else None


class CausalGraph:
    def __init__(self, timeline: Timeline):
        self.tl = timeline
        self.tl.sort()

    def _events_for(self, pid: int | None):
        if pid is None:
            return self.tl.events
        return [e for e in self.tl.events if e.pid == pid or e.pid is None]

    def why_exit(self, pid: int | None = None, baseline=None) -> CausalChain:
        """Explain why the process ended. ``baseline`` may be a :class:`DiffEngine`
        (working vs this broken run) whose first divergence becomes the root."""
        chain = CausalChain()
        events = self._events_for(pid)
        if not events:
            chain.steps.append(CausalStep("unknown", "no events captured", observed=False))
            return chain

        terminal = self.tl.terminal_event()
        if terminal is None:
            chain.steps.append(CausalStep("unknown", "no terminal event", observed=False))
            return chain

        tidx = self.tl.events.index(terminal)
        tid = terminal.tid

        # 1. the outcome
        if terminal.type == EventType.EXCEPTION:
            chain.steps.append(CausalStep(
                "exit", f"process died on an unhandled fault at T+{terminal.ts:.3f}s",
                event=terminal))
        elif terminal.type == EventType.PROCESS_EXIT:
            chain.steps.append(CausalStep(
                "exit", f"process exited at T+{terminal.ts:.3f}s", event=terminal))
        else:
            chain.steps.append(CausalStep(
                "exit", f"run ended at T+{terminal.ts:.3f}s (no exit event captured)",
                event=terminal, observed=False))

        confidence = 0.5
        evidence: list[str] = []

        # 2. the fault site + call stack (if the terminal is an exception)
        if terminal.type == EventType.EXCEPTION:
            mod = terminal.module or (parse_frame(terminal.stack[-1])[0] if terminal.stack else None)
            rva = terminal.rva
            owner = ownership.classify(mod) if mod else Owner.UNKNOWN
            site = f"{mod}+0x{rva:X}" if (mod and rva is not None) else (mod or "unknown site")
            chain.steps.append(CausalStep(
                "fault",
                f"fault in {site} [{owner.value}] {terminal.operation} {terminal.result}".strip(),
                owner=owner, event=terminal))
            confidence = 0.9
            evidence.append(f"fatal exception recorded at {site} ({owner.value})")

            # the stack, from the fault outward to the outermost caller
            if terminal.stack:
                frames = list(terminal.stack)
                # last frame is the crash site (already shown); walk callers outward
                for fr in reversed(frames[:-1]):
                    fmod, frva = parse_frame(fr)
                    fowner = ownership.classify(fmod) if fmod else Owner.UNKNOWN
                    chain.steps.append(CausalStep(
                        "called-from", f"reached via {fr} [{fowner.value}]",
                        owner=fowner))
                owners = {ownership.classify(parse_frame(f)[0]) for f in frames if parse_frame(f)[0]}
                if owners:
                    evidence.append("call path crosses: " + ", ".join(sorted(o.value for o in owners)))

        # 3. the thread
        if tid is not None:
            chain.steps.append(CausalStep("thread", f"on thread {tid}", event=terminal))

        # 4. the nearest preceding failed dependency (same thread if known, else same run)
        proximate = self._nearest_prior_failure(tidx, tid)
        if proximate is not None:
            powner = ownership.classify(proximate.module) if proximate.module else None
            suffix = f" [{powner.value}]" if powner and powner != Owner.UNKNOWN else ""
            chain.steps.append(CausalStep(
                "proximate", f"preceded by failure: {proximate.label()}{suffix}",
                owner=powner, event=proximate))
            evidence.append(f"nearest prior failure: {proximate.label()}")
            confidence = min(0.95, confidence + 0.03)

        # 5. the ultimate root -- only from a diff against a working run
        root_div = None
        if baseline is not None:
            try:
                root_div = baseline.first_divergence()
            except Exception:
                root_div = None
        if root_div is not None:
            chain.steps.append(CausalStep(
                "root",
                f"root cause vs working run: {root_div.description()} "
                f"(diff confidence {root_div.confidence})",
                observed=False,
                event=root_div.broken or root_div.working))
            evidence.append("root established by differential comparison with a working run")
            confidence = min(0.97, confidence)
        else:
            chain.steps.append(CausalStep(
                "unknown",
                "ultimate root (why the input to the faulting site was invalid) is "
                "UNKNOWN without a working run to diff against",
                observed=False))
            evidence.append("no working baseline supplied; root left UNKNOWN")

        chain.confidence = round(confidence, 3)
        chain.evidence = evidence
        return chain

    def _nearest_prior_failure(self, before_index: int, tid: int | None) -> BlackboxEvent | None:
        """The last failing, non-terminal event before ``before_index`` -- on the
        same thread when the tid is known, otherwise anywhere in the run."""
        for i in range(before_index - 1, -1, -1):
            ev = self.tl.events[i]
            if ev.is_terminal():
                continue
            if not ev.is_failure():
                continue
            if tid is not None and ev.tid is not None and ev.tid != tid:
                continue
            return ev
        return None
