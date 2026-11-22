"""Render offline trace analysis as plain text or structured data.

Two headline renderers: :func:`render_first_divergence` (the "FIRST DIVERGENCE"
block from a :class:`DiffEngine`) and :func:`render_why` (the causal evidence tree
from a :class:`CausalChain`). All output is deterministic plain text; a machine-
readable :func:`report_dict` mirrors the same facts.
"""
from __future__ import annotations

from .causal import CausalChain
from .diff import DiffEngine, Divergence
from .timeline import Timeline

_RULE = "-" * 54


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render_first_divergence(diff: DiffEngine) -> str:
    div = diff.first_divergence()
    lines = ["FIRST DIVERGENCE", _RULE]
    if div is None:
        lines.append("no divergence found: the two runs are equivalent under the")
        lines.append("event ontology (or one run has no events).")
        return "\n".join(lines)

    lines.append(f"T+{div.when:.6f}s")
    lines.append("")
    lines.append("Divergence:")
    lines.append(f"  {div.kind} -- {div.description()}")
    lines.append("")

    if div.working is not None:
        lines.append("Working run:")
        lines.append(f"  {div.working.label()}")
    else:
        lines.append("Working run:")
        lines.append("  (performed this step)" if div.kind == "working-only"
                     else "  (did not perform this)")
    lines.append("")

    lines.append("Broken run:")
    if div.broken is not None:
        lines.append(f"  {div.broken.label()}")
    else:
        lines.append("  (never performed this step)")
    lines.append("")

    side = div.broken or div.working
    if side is not None and (side.module or side.object):
        from . import ownership
        mod = side.module or side.object
        owner, why = ownership.explain(mod)
        lines.append("Owner:")
        lines.append(f"  {owner.value} -- {mod} ({why})")
        lines.append("")

    lines.append("Confidence:")
    lines.append(f"  {_pct(div.confidence)}")
    lines.append("")
    lines.append("Evidence:")
    for e in div.evidence:
        lines.append(f"  - {e}")
    lines.append("")
    lines.append("Downstream:")
    lines.append(f"  {diff.downstream_count(div)} difference(s) suppressed")
    return "\n".join(lines)


def render_why(chain: CausalChain) -> str:
    lines = ["WHY THE PROCESS ENDED", _RULE]
    if not chain.steps:
        lines.append("no causal chain (no events).")
        return "\n".join(lines)
    for depth, step in enumerate(chain.steps):
        if depth == 0:
            prefix = ""
        else:
            prefix = "   " * (depth - 1) + "└─ "
        tag = "" if step.observed else "  [inferred]"
        lines.append(f"{prefix}{step.text}{tag}")
    lines.append("")
    lines.append(f"Confidence (proximate attribution): {_pct(chain.confidence)}")
    lines.append("Evidence:")
    for e in chain.evidence:
        lines.append(f"  - {e}")
    return "\n".join(lines)


def render_owner_breakdown(diff: DiffEngine, window: float | None = None) -> str:
    rows = diff.owner_breakdown(window=window)
    scope = f"last {window:g}s" if window else "whole broken run"
    lines = [f"OWNER BREAKDOWN ({scope})", _RULE]
    for owner, n, frac in rows:
        lines.append(f"  {_pct(frac):>6}  {owner.value:<12} ({n})")
    return "\n".join(lines)


def render_timeline(tl: Timeline, limit: int | None = None, **filters) -> str:
    events = tl.filter(**filters) if filters else tl.events
    if limit:
        events = events[:limit]
    lines = [f"TIMELINE {tl.label!r} outcome={tl.outcome!r} ({len(tl)} events)", _RULE]
    for ev in events:
        flag = "!" if ev.is_failure() else " "
        lines.append(f"{flag}T+{(ev.ts or 0.0):9.6f} [{ev.source:<9}] {ev.label()}")
    return "\n".join(lines)


def report_dict(working: Timeline, broken: Timeline) -> dict:
    """Structured mirror of the text report, for machine consumers."""
    from .causal import CausalGraph

    diff = DiffEngine(working, broken)
    div = diff.first_divergence()
    chain = CausalGraph(broken).why_exit(baseline=diff)
    return {
        "schema": "nyr-blackbox-report/1",
        "working": working.label,
        "broken": broken.label,
        "first_divergence": None if div is None else {
            "kind": div.kind,
            "when": div.when,
            "description": div.description(),
            "confidence": div.confidence,
            "evidence": div.evidence,
            "downstream_suppressed": diff.downstream_count(div),
        },
        "why": {
            "confidence": chain.confidence,
            "steps": [
                {"relation": s.relation, "text": s.text,
                 "owner": s.owner.value if s.owner else None, "observed": s.observed}
                for s in chain.steps
            ],
            "evidence": chain.evidence,
        },
        "owner_breakdown": [
            {"owner": o.value, "count": n, "fraction": f}
            for o, n, f in diff.owner_breakdown()
        ],
    }


def render_full(working: Timeline, broken: Timeline) -> str:
    from .causal import CausalGraph

    diff = DiffEngine(working, broken)
    chain = CausalGraph(broken).why_exit(baseline=diff)
    parts = [
        render_first_divergence(diff),
        "",
        render_owner_breakdown(diff),
        "",
        render_why(chain),
    ]
    return "\n".join(parts)
