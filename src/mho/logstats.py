"""Offline summaries of simulation, zone, and health events in server logs.

The reader counts complete timestamped entries and measures tick timing, zone
stage duration, memory use, and other statistics already written by a run."""
from __future__ import annotations

import collections
import re
from typing import Iterable, Iterator

ENTRY = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) - (Trace|Debug|Info|Error) - (.*)$")
AI_STOPPED = re.compile(
    r"HuntDirector: hunt (\d+) \(session (\d+)\): monster AI stopped after (\d+) steps: ([\d.]+) Hz, (\d+) late \(over [\d.]+ periods\), "
    r"the longest gap ([\d.]+) ms, a step took ([\d.]+) ms on average, ([\d.]+) ms at most")
ZONE_ENDING = re.compile(r"zone (\d+): ending \((\w+)\): \d+ \w+:(.*)$")
STAGE = re.compile(r"\b(Loading|Initializing|Spawning|Active|Cleanup) ([\d.]+) (ms|s)\b")
HEALTH = re.compile(
    r"ServerHealth: health: (\d+) connection\(s\), (\d+) town session\(s\), (\d+) hunt\(s\), (\d+) part\(ies\), (\d+) field world\(s\), (\d+) zone\(s\) open \| "
    r"(\d+) threads, (\d+) handles, (\d+) MB working set, (\d+) MB managed, gc (\d+)/(\d+)/(\d+) \| up (\d+) s")
HEALTH_FIELDS = ("connections", "town_sessions", "hunts", "parties", "field_worlds", "zones_open", "threads", "handles", "working_set_mb", "managed_mb",
                 "gc0", "gc1", "gc2", "uptime_s")
STAGES = ("Loading", "Initializing", "Spawning", "Active", "Cleanup")
# Errors from the transport and its own connection-event consumers.
TRANSPORT_ERROR = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d - Error - (?:WorldTransport\w*\b|(?:SessionConsumer|ZoneConsumer): .*\bclient does not exist in lookup)", re.IGNORECASE)


def transport_errors(text: str) -> list[str]:
    """The Error entries of a server log that belong to the transport (or to the consumers of its events); the lines of a stack trace under one are not counted."""
    return [line.rstrip("\r") for line in text.split("\n") if TRANSPORT_ERROR.match(line)]


def percentile(values: list[float], p: float) -> float:
    """The nearest-rank percentile of ``values`` (0 for none)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))             # ceil(n * p / 100)
    return float(ordered[int(rank) - 1])


def spread(values: list[float]) -> dict:
    """How a measure is distributed: how many, the smallest, the median, the 95th and 99th percentile, the largest."""
    if not values:
        return {"n": 0, "min": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {"n": len(values), "min": round(min(values), 3), "p50": round(percentile(values, 50), 3), "p95": round(percentile(values, 95), 3),
            "p99": round(percentile(values, 99), 3), "max": round(max(values), 3)}


def read_lines(path: str) -> Iterator[str]:
    """The lines of a log file, read as the UTF-8 the server writes (a byte that is not is replaced, never fatal), a line end stripped."""
    with open(path, "rb") as f:
        for raw in f:
            yield raw.decode("utf-8", "replace").rstrip("\r\n")


def _milliseconds(amount: str, unit: str) -> float:
    return float(amount) * (1000.0 if unit == "s" else 1.0)


def analyse(lines: Iterable[str]) -> dict:
    """The numbers of a log: entries by level and time span, the AI clock of every hunt, the stages of every zone, and the health series."""
    levels: collections.Counter = collections.Counter()
    first = last = None
    ai: list[dict] = []
    zones: list[dict] = []
    exits: collections.Counter = collections.Counter()
    health: list[dict] = []
    for line in lines:
        m = ENTRY.match(line)
        if not m:
            continue
        stamp, level, text = m.groups()
        levels[level] += 1
        first = first or stamp
        last = stamp
        if "monster AI stopped" in text:
            a = AI_STOPPED.search(text)
            if a:
                ai.append({"hunt": int(a[1]), "session": int(a[2]), "steps": int(a[3]), "hz": float(a[4]), "late": int(a[5]), "longest_gap_ms": float(a[6]),
                           "step_avg_ms": float(a[7]), "step_max_ms": float(a[8])})
        elif ": ending (" in text:
            z = ZONE_ENDING.search(text)
            if z:
                stages = {name: _milliseconds(amount, unit) for name, amount, unit in STAGE.findall(z[3])}
                zones.append({"level": int(z[1]), "exit": z[2], "stages": stages})
                exits[z[2]] += 1
        elif "ServerHealth: health:" in text:
            h = HEALTH.search(text)
            if h:
                health.append({"time": stamp, **dict(zip(HEALTH_FIELDS, (int(x) for x in h.groups())))})
    steps = sum(a["steps"] for a in ai)
    late = sum(a["late"] for a in ai)
    return {
        "entries": sum(levels.values()), "levels": dict(levels), "first": first, "last": last,
        "ai": {"hunts": len(ai), "steps": steps, "late": late, "late_share": round(late / steps, 6) if steps else 0.0,
               "hz": spread([a["hz"] for a in ai]), "longest_gap_ms": spread([a["longest_gap_ms"] for a in ai]),
               "step_avg_ms": spread([a["step_avg_ms"] for a in ai]), "step_max_ms": spread([a["step_max_ms"] for a in ai])},
        "zones": {"ended": len(zones), "exits": dict(exits),
                  "stages_ms": {name: spread([z["stages"][name] for z in zones if name in z["stages"]]) for name in STAGES}},
        "health": {"snapshots": len(health), "first": health[0] if health else None, "last": health[-1] if health else None,
                   **{field: spread([float(h[field]) for h in health]) for field in ("connections", "town_sessions", "hunts", "threads", "handles",
                                                                                      "working_set_mb", "managed_mb")}},
    }


def _row(label: str, s: dict, unit: str = "") -> str:
    if not s["n"]:
        return f"    {label:<14} none"
    return f"    {label:<14} n={s['n']:<6} min {s['min']:g}  p50 {s['p50']:g}  p95 {s['p95']:g}  p99 {s['p99']:g}  max {s['max']:g}{unit}"


def render(stats: dict, name: str = "") -> list[str]:
    """The numbers as the lines a person reads."""
    lv = stats["levels"]
    out = [f"log {name}".rstrip(),
           f"  {stats['entries']} entries, {stats['first']} .. {stats['last']}: " + ", ".join(f"{lv.get(k, 0)} {k}" for k in ("Trace", "Debug", "Info", "Error"))]
    ai = stats["ai"]
    out.append(f"  monster AI: {ai['hunts']} hunts, {ai['steps']} steps, {ai['late']} late ({ai['late_share'] * 100:.3f}%)")
    out += [_row("clock Hz", ai["hz"]), _row("longest gap", ai["longest_gap_ms"], " ms"), _row("step average", ai["step_avg_ms"], " ms"), _row("step at most", ai["step_max_ms"], " ms")]
    z = stats["zones"]
    out.append(f"  zones: {z['ended']} ended ({', '.join(f'{n} {k}' for k, n in sorted(z['exits'].items()))})")
    out += [_row(name, z["stages_ms"][name], " ms") for name in STAGES]
    h = stats["health"]
    out.append(f"  health: {h['snapshots']} snapshots")
    if h["snapshots"]:
        for label, field, unit in (("threads", "threads", ""), ("handles", "handles", ""), ("working set", "working_set_mb", " MB"), ("managed", "managed_mb", " MB"),
                                   ("connections", "connections", ""), ("town sessions", "town_sessions", ""), ("hunts", "hunts", "")):
            out.append(_row(label, h[field], unit))
        first, last = h["first"], h["last"]
        out.append(f"    first -> last: working set {first['working_set_mb']} -> {last['working_set_mb']} MB, managed {first['managed_mb']} -> {last['managed_mb']} MB, "
                   f"threads {first['threads']} -> {last['threads']}, handles {first['handles']} -> {last['handles']}, up {last['uptime_s']} s")
    return out
