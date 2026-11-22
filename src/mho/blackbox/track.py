"""Offline analysis of JSONL movement traces.

Rows have an event kind in 'e' and a time in seconds in 't'. Position
reports contain 'p' as [x, y, z]. Monster samples use the 'mon' event with
'id', 'x', 'y', 'z', and optional 'yaw' and 'anim' fields. Predicted
positions use 'trk' with 'x' and 'y'. The tests generate sample traces.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict


POSITION_KINDS = ("fifo", "move", "begin", "stop", "idle")
REOPEN_AFTER = 0.3
FROZEN_AFTER = 5.0


def load(path: str) -> tuple[list[dict], int]:
    """The rows of a recording and how many lines could not be read (a hunt cut off mid-line)."""
    rows, bad = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(row, dict) and "e" in row and "t" in row:
                rows.append(row)
            else:
                bad += 1
    return rows, bad


def _pos(row: dict) -> tuple[float, float, float] | None:
    p = row.get("p")
    if isinstance(p, list) and len(p) == 3 and all(isinstance(v, (int, float)) for v in p):
        return float(p[0]), float(p[1]), float(p[2])
    return None


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def summary(rows: list[dict]) -> dict:
    """Count events and measure position report gaps and horizontal speeds."""
    counts = Counter(r["e"] for r in rows)
    fixes = [(r["t"], _pos(r)) for r in rows if r["e"] in POSITION_KINDS and _pos(r) is not None]
    gaps = [b[0] - a[0] for a, b in zip(fixes, fixes[1:]) if b[0] > a[0]]
    speeds = []
    for (t0, p0), (t1, p1) in zip(fixes, fixes[1:]):
        if t1 - t0 >= 0.04 and math.dist(p0[:2], p1[:2]) < 30.0:
            speeds.append(math.dist(p0[:2], p1[:2]) / (t1 - t0))
    duration = max((r["t"] for r in rows), default=0.0)
    skills = Counter((r.get("id"), r.get("name")) for r in rows if r["e"] == "skill")
    return {
        "duration_s": round(duration, 1),
        "events": dict(counts),
        "position_reports_per_s": round(len(fixes) / duration, 2) if duration else 0.0,
        "report_gap_s": {"median": round(_percentile(gaps, 0.5), 3), "p95": round(_percentile(gaps, 0.95), 3), "max": round(max(gaps, default=0.0), 3)},
        "hunter_speed_mps": {"median": round(_percentile(speeds, 0.5), 2), "p95": round(_percentile(speeds, 0.95), 2), "max": round(max(speeds, default=0.0), 2)},
        "skill_events": {f"{i}:{n}": c for (i, n), c in skills.most_common(40)},
    }


def evades(
    rows: list[dict], *, dodge_skills: frozenset[int], perfect_skill: int,
    dodge_state: int | str, perfect_marker: str = "PerfectEvade",
) -> list[dict]:
    """Recover dodge windows from ordered events and caller-provided skill IDs.

    The window opens at a dodge start, a matching marker, or a matching state
    report. Each result includes the time range, movement, nearest monster
    sample, last state report, and time until the next position update.
    """
    windows: list[dict] = []
    current: dict | None = None
    monsters = [r for r in rows if r["e"] == "mon" and isinstance(r.get("d"), (int, float))]
    for r in rows:
        kind = r["e"]
        opens = kind == "skill" and ((r.get("id") in dodge_skills and r.get("name") == "Start") or str(r.get("name", "")).startswith(perfect_marker))
        if kind == "fifo" and r.get("type") == dodge_state and r.get("skill") in dodge_skills | {perfect_skill}:
            opens = opens or not windows or windows[-1]["end"] is None or r["t"] - windows[-1]["end"] > REOPEN_AFTER
        if opens and current is None:
            current = {"start": r["t"], "end": None, "events": [], "perfect": False, "skills": set()}
            windows.append(current)
        if current is not None:
            if kind == "skill":
                current["events"].append(f"{r.get('id')}/{r.get('lvl')}:{r.get('name')}")
                current["skills"].add(r.get("id"))
                if str(r.get("name", "")).startswith(perfect_marker):
                    current["perfect"] = True
            if kind == "fifo" and r.get("skill") == perfect_skill:
                current["perfect"] = True
            if kind == "evade_end":
                current["end"] = r["t"]
                current = None
    for w in windows:
        stop = w["end"] if w["end"] is not None else w["start"] + 3.0
        w["duration"] = round(stop - w["start"], 3) if w["end"] is not None else None
        near = [m["d"] for m in monsters if w["start"] - 0.2 <= m["t"] <= stop + 0.2]
        w["closest_monster_m"] = round(min(near), 1) if near else None
        moved = [(r["t"], _pos(r)) for r in rows if r["e"] in POSITION_KINDS and _pos(r) is not None and w["start"] - 0.3 <= r["t"] <= stop + 0.3]
        w["moved_m"] = round(math.dist(moved[0][1][:2], moved[-1][1][:2]), 1) if len(moved) >= 2 else None
        w["skills"] = sorted(s for s in w["skills"] if s is not None)
        w["last_state"] = _last_state(rows, stop)
        after = next((r["t"] for r in rows if r["e"] in POSITION_KINDS and r["t"] > stop), None)
        w["silent_to_end"] = after is None
        w["quiet_after"] = round((after if after is not None else max((r["t"] for r in rows), default=stop)) - stop, 3)
    return windows


def frozen(windows: list[dict]) -> list[dict]:
    """The dodges after which the client sent no position report for :data:`FROZEN_AFTER` seconds or more: a hunter it may have left in a state."""
    return [w for w in windows if w["quiet_after"] >= FROZEN_AFTER]


def _last_state(rows: list[dict], t: float) -> dict | None:
    """The state words, skill and stamina of the last ``fifo`` sync at or before ``t``."""
    last = None
    for r in rows:
        if r["e"] == "fifo" and r["t"] <= t:
            last = r
        elif r["t"] > t:
            break
    if last is None:
        return None
    return {"t": last["t"], "s": last.get("s"), "ag": last.get("ag"), "skill": last.get("skill"), "sta": last.get("sta"), "type": last.get("type")}


def unfinished(windows: list[dict]) -> list[dict]:
    """The evades whose end the client never reported: the ones where a hunter may have been left in the state."""
    return [w for w in windows if w["end"] is None]


def around(rows: list[dict], t: float, window: float = 2.0, kinds: tuple[str, ...] | None = None) -> list[str]:
    """A readable timeline of everything within ``window`` seconds of ``t`` (optionally only some kinds)."""
    out = []
    for r in rows:
        if abs(r["t"] - t) > window or (kinds and r["e"] not in kinds):
            continue
        body = {k: v for k, v in r.items() if k not in ("t", "e")}
        out.append(f"{r['t']:8.3f}  {r['e']:9} " + json.dumps(body, separators=(",", ":"), ensure_ascii=False))
    return out


def monster_turns(rows: list[dict]) -> dict[int, dict]:
    """Measure per-entity yaw changes in degrees per second, accounting for wraparound."""
    last: dict[int, tuple[float, float]] = {}
    rates: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        if r["e"] != "mon" or not isinstance(r.get("yaw"), (int, float)):
            continue
        mid = r.get("id")
        if mid in last and r["t"] > last[mid][0]:
            turn = (r["yaw"] - last[mid][1] + 180.0) % 360.0 - 180.0
            rates[mid].append(abs(turn) / (r["t"] - last[mid][0]))
        last[mid] = (r["t"], r["yaw"])
    return {mid: {"max_dps": round(max(v), 1), "p99_dps": round(_percentile(v, 0.99), 1), "samples": len(v)} for mid, v in rates.items() if v}


def clip_turn_rates(profile: dict) -> dict[str, float]:
    """Find each supplied animation clip's fastest turn from its yaw keys."""
    clips = profile.get("clips") if isinstance(profile, dict) else None
    out: dict[str, float] = {}
    for name, clip in (clips.items() if isinstance(clips, dict) else ()):
        yaw = clip.get("yaw") if isinstance(clip, dict) else None
        pts = [p for p in yaw if isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)] \
            if isinstance(yaw, list) else []
        best = 0.0
        for (t0, a0), (t1, a1) in zip(pts, pts[1:]):
            if t1 > t0:
                best = max(best, abs(a1 - a0) / (t1 - t0))
        out[str(name).lower()] = best
    return out


def turn_causes(rows: list[dict], clip_rates: dict[str, float], threshold: float = 200.0, keep: int = 10) -> dict[int, dict]:
    """Compare high observed turn rates with the supplied animation rates.

    A nearby clip accounts for the turn when its peak yaw rate is at least
    half the observed rate. This heuristic identifies candidates for review.
    """
    last: dict[int, dict] = {}
    out: dict[int, dict] = {}
    for r in rows:
        if r.get("e") != "mon" or not isinstance(r.get("yaw"), (int, float)) or not isinstance(r.get("t"), (int, float)):
            continue
        mid = r.get("id")
        prev = last.get(mid)
        if prev is not None and r["t"] > prev["t"]:
            stat = out.setdefault(mid, {"samples": 0, "fast": 0, "explained": 0, "unexplained": [], "unexplained_count": 0})
            stat["samples"] += 1
            rate = abs((r["yaw"] - prev["yaw"] + 180.0) % 360.0 - 180.0) / (r["t"] - prev["t"])
            if rate > threshold:
                stat["fast"] += 1
                clip = max(clip_rates.get(str(r.get("anim") or "").lower(), 0.0), clip_rates.get(str(prev.get("anim") or "").lower(), 0.0))
                if clip >= 0.5 * rate:
                    stat["explained"] += 1
                else:
                    stat["unexplained_count"] += 1
                    if len(stat["unexplained"]) < keep:
                        stat["unexplained"].append({"t": r["t"], "dps": round(rate), "was": prev.get("anim"), "anim": r.get("anim"), "clip_dps": round(clip)})
        last[mid] = r
    return out


def tracking_error(rows: list[dict]) -> dict:
    """Compare predicted and last-reported positions with an interpolated reference.

    The reference uses consecutive position reports up to one second apart.
    """
    fixes = [(r["t"], _pos(r)) for r in rows if r["e"] in POSITION_KINDS and _pos(r) is not None]
    if len(fixes) < 2:
        return {}
    followed, stale = [], []
    j = 0
    for r in rows:
        if r["e"] != "trk" or "x" not in r:
            continue
        while j + 1 < len(fixes) and fixes[j + 1][0] < r["t"]:
            j += 1
        if j + 1 >= len(fixes):
            break
        (t0, p0), (t1, p1) = fixes[j], fixes[j + 1]
        if not (t0 <= r["t"] <= t1) or t1 - t0 > 1.0 or t1 <= t0:
            continue
        k = (r["t"] - t0) / (t1 - t0)
        truth = (p0[0] + (p1[0] - p0[0]) * k, p0[1] + (p1[1] - p0[1]) * k)
        followed.append(math.dist((r["x"], r["y"]), truth))
        stale.append(math.dist(p0[:2], truth))
    if not followed:
        return {}
    return {
        "samples": len(followed),
        "followed_m": {"mean": round(sum(followed) / len(followed), 2), "p95": round(_percentile(followed, 0.95), 2)},
        "last_report_m": {"mean": round(sum(stale) / len(stale), 2), "p95": round(_percentile(stale, 0.95), 2)},
    }


def ground_error(rows: list[dict], terrain) -> dict[int, dict]:
    """Compare altitude with the supplied terrain.height(x, y) function."""
    errors: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        if r["e"] == "mon" and all(isinstance(r.get(k), (int, float)) for k in ("x", "y", "z")):
            h = terrain.height(r["x"], r["y"])
            if h is not None:
                errors[r["id"]].append(abs(r["z"] - h))
    return {mid: {"median_m": round(_percentile(v, 0.5), 2), "p95_m": round(_percentile(v, 0.95), 2), "samples": len(v)} for mid, v in errors.items()}


def outside_regions(rows: list[dict], contains) -> dict[int, int]:
    """The samples where a monster stood outside the ground it may walk on: ``contains(x, y)`` says whether a point is inside its region (a caller
    knows the scene's polygons); counted per monster."""
    out: dict[int, int] = defaultdict(int)
    for r in rows:
        if r["e"] == "mon" and isinstance(r.get("x"), (int, float)) and isinstance(r.get("y"), (int, float)) and not contains(r["x"], r["y"]):
            out[r["id"]] += 1
    return dict(out)
