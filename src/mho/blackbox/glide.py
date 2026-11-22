"""Measure movement, animation paths, and placement intervals from sample data.

The analysis consumes caller-supplied trace rows and motion profiles. A profile
may describe animation position keys, named gait speeds, and authored behavior
actions. See the synthetic profiles in the tests for the supported shapes.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional


MOVING_MPS = 0.3
OFF_FACING_DEG = 45.0
ROOT_MOTION_MPS = 0.5
MAX_STEP_S = 0.5
MIN_MOVED_M = 5.0
TELEPORT_MPS = 300.0
GLIDE_WATCH_SHARE = 0.10
OVER_SPEED_RATIO = 1.25
OVER_SPEED_MIN_S = 1.0
OVER_SPEED_MIN_M = 5.0
STALE_LIMIT_M = 0.17
BEHIND_SHARE = 0.9
FASTEST_MIN_S = 1.0


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def _resolve(value, blackboard: dict) -> tuple:
    """(number or None, unresolved name or None) of one ``Value`` of a ``SetState MoveSpeed`` action."""
    text = str(value if value is not None else "").strip()
    if text.startswith("state."):
        name = text.removeprefix("state.")
        entry = blackboard.get(name)
        raw = str(entry.get("value", "")).strip() if isinstance(entry, dict) else ""
        try:
            return float(raw), None
        except ValueError:
            return None, name
    try:
        return float(text or 0), None
    except ValueError:
        return None, text


def _speed_of(attrs: dict, blackboard: dict) -> tuple:
    """(speed m/s or None, unresolved name or None) of a ``SetState MoveSpeed`` action (the length of its vector)."""
    parts, missing = [], None
    for key in ("Value1", "Value2", "Value3"):
        number, name = _resolve(attrs.get(key), blackboard)
        if name is not None:
            missing = missing or name
        else:
            parts.append(number or 0.0)
    if missing is not None:
        return None, missing
    return math.sqrt(sum(p * p for p in parts)), None


def _is_set_speed(node: dict) -> bool:
    a = node.get("a") or {}
    return node.get("t") == "Action" and a.get("Operation") == "SetState" and a.get("KeyName") == "MoveSpeed"


def _walk_speeds(node: dict, blackboard: dict, speeds: set, unresolved: set) -> None:
    if _is_set_speed(node):
        speed, missing = _speed_of(node.get("a") or {}, blackboard)
        if missing is not None:
            unresolved.add(missing)
        elif speed and speed > 0.01:
            speeds.add(round(speed, 3))
    for child in node.get("c") or []:
        if isinstance(child, dict):
            _walk_speeds(child, blackboard, speeds, unresolved)


def _pair_speeds(node: dict, blackboard: dict, out: dict, seen_unresolved: set) -> None:
    """Within every sequence: the animations it plays itself (``PlayClip`` children) get the speeds set anywhere beneath it."""
    kids = [c for c in (node.get("c") or []) if isinstance(c, dict)]
    if node.get("t") == "Sequence":
        anims = [str((k.get("a") or {}).get("Clip")) for k in kids
                 if k.get("t") == "Action" and (k.get("a") or {}).get("Operation") == "PlayClip" and (k.get("a") or {}).get("Clip")]
        if anims:
            speeds, unresolved = set(), set()
            for k in kids:
                _walk_speeds(k, blackboard, speeds, unresolved)
            for a in anims:
                entry = out.setdefault(a.lower(), {"set": set(), "unresolved": set()})
                entry["set"] |= speeds
                entry["unresolved"] |= unresolved
    for k in kids:
        _pair_speeds(k, blackboard, out, seen_unresolved)


def _path_speed(pos: list, duration: float) -> float:
    """Divide the length of the horizontal animation path by the clip's duration."""
    if not isinstance(pos, list) or len(pos) < 2 or not duration or duration <= 0.05:
        return 0.0
    total = 0.0
    for a, b in zip(pos, pos[1:]):
        if isinstance(a, list) and isinstance(b, list) and len(a) >= 3 and len(b) >= 3:
            total += math.hypot((_num(b[1]) or 0.0) - (_num(a[1]) or 0.0), (_num(b[2]) or 0.0) - (_num(a[2]) or 0.0))
    return total / duration


def peak_speed(pos: list, window: float = 0.1) -> float:
    """Find the largest horizontal speed between animation keys separated by the sample window."""
    keys = [(_num(p[0]) or 0.0, _num(p[1]) or 0.0, _num(p[2]) or 0.0) for p in pos if isinstance(p, list) and len(p) >= 3] if isinstance(pos, list) else []
    best = 0.0
    for i, (t0, x0, y0) in enumerate(keys):
        for t1, x1, y1 in keys[i + 1:]:
            if t1 - t0 >= window - 1e-9:
                best = max(best, math.hypot(x1 - x0, y1 - y0) / (t1 - t0))
                break
    return best


def _net_speed(pos: list, duration: float) -> float:
    """Divide the absolute net forward displacement by the clip's duration."""
    if not isinstance(pos, list) or len(pos) < 2 or not duration or duration <= 0.05:
        return 0.0
    first, last = pos[0], pos[-1]
    if isinstance(first, list) and isinstance(last, list) and len(first) >= 3 and len(last) >= 3:
        return abs((_num(last[2]) or 0.0) - (_num(first[2]) or 0.0)) / duration
    return 0.0


def _sets_angry_speed(node: dict) -> bool:
    """Check whether an authored action applies the supplied animation speed modifier."""
    attrs = node.get("a") if isinstance(node.get("a"), dict) else {}
    if attrs.get("Operation") == "CopyStateNumber" and attrs.get("KeyName1") == "SkillSpeed" and attrs.get("KeyName2") == "AggroRateMultiplier":
        return True
    return any(isinstance(k, dict) and _sets_angry_speed(k) for k in node.get("c") or [])


def _blackboard_float(blackboard: dict, key: str) -> Optional[float]:
    entry = blackboard.get(key)
    if isinstance(entry, dict):
        try:
            return float(str(entry.get("value", "")).strip())
        except ValueError:
            return None
    return None


def motion_table(profile: dict) -> dict:
    """Summarize caller-supplied animation, gait, and behavior data.

    The result stores each clip's total path speed, net forward speed,
    duration, and speeds from adjacent behavior actions. Missing values
    remain listed as unresolved.
    """
    if not isinstance(profile, dict):
        return {"anims": {}, "unresolved": [], "gaits": {}, "gait_driven": False, "angry": None}
    blackboard = profile.get("blackboard") if isinstance(profile.get("blackboard"), dict) else {}
    anims: dict = {}
    clips = profile.get("clips") if isinstance(profile.get("clips"), dict) else {}
    for name, clip in clips.items():
        if isinstance(clip, dict):
            dur = _num(clip.get("dur")) or 0.0
            anims[str(name).lower()] = {"root": round(_path_speed(clip.get("pos"), dur), 3), "net": round(_net_speed(clip.get("pos"), dur), 3),
                                        "dur": round(dur, 3), "set": [], "unresolved": []}
    paired: dict = {}
    trees = profile.get("trees") if isinstance(profile.get("trees"), dict) else {}
    every_unresolved: set = set()
    for tree in trees.values():
        if isinstance(tree, dict):
            _pair_speeds(tree, blackboard, paired, every_unresolved)
            _walk_speeds(tree, blackboard, set(), every_unresolved)
    for name, entry in paired.items():
        slot = anims.setdefault(name, {"root": 0.0, "net": 0.0, "dur": 0.0, "set": [], "unresolved": []})
        slot["set"] = sorted(entry["set"])
        slot["unresolved"] = sorted(entry["unresolved"])
    gaits = {}
    for key, entry in blackboard.items():
        if isinstance(entry, dict) and (key.startswith("MoveSpeed_") or (key.startswith("Max") and key.endswith("Speed") and "Rotate" not in key)):
            try:
                value = float(str(entry.get("value", "")).strip())
            except ValueError:
                continue
            gaits[key] = value
    scale, seconds = _blackboard_float(blackboard, "AggroRateMultiplier"), _blackboard_float(blackboard, "AggroDuration")
    angry = ({"scale": scale, "seconds": seconds} if scale and scale > 1.0 and seconds and seconds > 0 and any(isinstance(t, dict) and _sets_angry_speed(t) for t in trees.values())
             else None)
    return {"anims": anims, "unresolved": sorted(every_unresolved), "gaits": gaits, "gait_driven": any(k.startswith("MoveSpeed_") for k in gaits), "angry": angry}


def candidate_gait(table: Optional[dict], anim: str) -> Optional[tuple]:
    """Find a supplied gait speed whose key matches an animation name prefix."""
    if not table or not anim or not anim.lower().startswith("move_"):
        return None
    gaits = table.get("gaits") or {}
    keys = {k.lower(): k for k in gaits if k.startswith("MoveSpeed_")}
    gait = anim[5:]
    while gait:
        key = keys.get("movespeed_" + gait.lower())
        if key is not None:
            return key, gaits[key]
        cut = gait.rfind("_")
        if cut <= 0:
            break
        gait = gait[:cut]
    return None


def _heading_off(dx: float, dy: float, yaw: float) -> float:
    """The angle in degrees between the way a step went and the way the monster faced (yaw 0 faces +y)."""
    heading = math.degrees(math.atan2(dy, dx))
    return abs((heading - 90.0 - yaw + 180.0) % 360.0 - 180.0)


def monster_series(rows: list) -> dict:
    """The ``mon`` rows of a recording by monster id: [(t, x, y, yaw, anim, distance)] oldest first. A row with a non-numeric position is skipped."""
    out: dict = defaultdict(list)
    for r in rows:
        if r.get("e") != "mon":
            continue
        t, x, y = _num(r.get("t")), _num(r.get("x")), _num(r.get("y"))
        if t is None or x is None or y is None:
            continue
        out[r.get("id")].append((t, x, y, _num(r.get("yaw")), str(r.get("anim") or ""), _num(r.get("d"))))
    return dict(out)


def _kind(table: Optional[dict], anim: str) -> str:
    """How the data accounts for a monster moving in an animation:

    * ``root``    -- the clip moves the root;
    * ``set``     -- a tree sets the speed next to the animation;
    * ``nodata``  -- neither, but the data names speeds it does not tie to the animation (a speed per gait -- ``MoveSpeed_Walk`` / ``_Fly`` ... -- or a ``state.`` name
                     with no value): the monster is *driven* at a speed the data does not say, so there is nothing to hold the measurement against;
    * ``none``    -- neither, and the data names nothing: movement the data does not account for;
    * ``unnamed`` -- the recording names no animation;
    * ``noprofile`` -- the monster has no profile."""
    if table is None:
        return "noprofile"
    if not anim:
        return "unnamed"
    entry = table["anims"].get(anim.lower())
    if entry and entry["root"] >= ROOT_MOTION_MPS:
        return "root"
    if entry and entry["set"]:
        return "set"
    if table.get("gait_driven") or (entry and entry["unresolved"]):
        return "nodata"
    return "none"


def gait_matches(table: Optional[dict], mps: float) -> list:
    """The names of the entity's own speeds (``MoveSpeed_*`` and ``Max*Speed`` of its blackboard) that a measured speed equals, within 5 %."""
    if not table or mps <= 0:
        return []
    return sorted(k for k, v in table["gaits"].items() if v > 0 and abs(mps - v) <= 0.05 * v)


def _runs(series: list) -> list:
    """The runs of one monster's rows -- consecutive rows of one animation with no gap: [(anim, seconds, path metres)]."""
    out: list = []
    run = None
    for row in series:
        step = math.hypot(row[1] - run["x"], row[2] - run["y"]) if run else 0.0
        if run and row[4] == run["anim"] and 0 < row[0] - run["t"] <= MAX_STEP_S and step / (row[0] - run["t"]) <= TELEPORT_MPS:    # a teleport ends a run
            run["m"] += step
            run["t"], run["x"], run["y"] = row[0], row[1], row[2]
        else:
            run = {"anim": row[4], "t0": row[0], "t": row[0], "x": row[1], "y": row[2], "m": 0.0}
            out.append(run)
    return [(r["anim"], r["t"] - r["t0"], r["m"]) for r in out]


def angry_windows(series: list, table: Optional[dict]) -> list:
    """The time spans ``[(begin, end)]`` of a monster's enrage: from each start of its ``Emotion_Angry`` animation for the ``AggroDuration`` its data states. Empty for a monster
    whose data has no enrage speed-up (or no profile)."""
    angry = (table or {}).get("angry")
    if not angry:
        return []
    out, previous = [], None
    for row in series:
        playing = str(row[4] or "").lower() == "emotion_angry"
        if playing and not previous:
            out.append((row[0], row[0] + angry["seconds"]))
        previous = playing
    return out


def _data_speed(slot: dict) -> Optional[dict]:
    """The number the data gives for an animation, set beside what was measured: ``{"data", "measured", "seconds", "metres", "basis", "inferred"}`` or None when the data
    gives none. ``root``: the clip's path over its length (and any tree speed set beside it, the higher of the two) against the animation's average over *every* step of it;
    ``set``: the highest speed a tree sets against the mean of the moving steps; ``nodata`` with a gait named by the clip: that ``MoveSpeed_<gait>`` (inferred -- see
    :func:`candidate_gait`) against the mean of the moving steps."""
    kind = slot.get("kind")
    root, sets = slot.get("root_mps") or 0.0, list(slot.get("set_mps") or [])
    if kind == "root":
        scale, share = slot.get("angry_scale") or 1.0, _share(slot.get("all_angry_s"), slot.get("all_s") or 0.0)
        effective = root * (1.0 + (scale - 1.0) * share)
        data = max([effective] + sets)
        basis = (f"its clip's root motion is {root:g} m/s"
                 + (f", {effective:.4g} m/s with the data's enrage speed-up (AggroRateMultiplier {scale:g}, {share:.0%} of the animation was inside an enrage window)" if share > 0 else "")
                 + (f" and a tree sets {_speeds_text(sets)} m/s" if sets else ""))
        return {"data": data, "measured": slot["all_mps"], "seconds": slot["all_s"], "metres": slot["all_m"], "basis": basis, "inferred": False}
    if kind == "set" and sets:
        return {"data": max(sets), "measured": slot["mean_mps"], "seconds": slot["s"], "metres": slot["m"], "basis": f"a tree sets {_speeds_text(sets)} m/s" + (" (the highest is the bar)" if len(sets) > 1 else ""),
                "inferred": False}
    gait = slot.get("gait")
    if kind == "nodata" and gait and gait[1] > 0:
        return {"data": gait[1], "measured": slot["mean_mps"], "seconds": slot["s"], "metres": slot["m"],
                "basis": f"by its name the gait is {gait[0][len('MoveSpeed_'):]}: {gait[0]} {gait[1]:g} m/s", "inferred": True}
    return None


def _speeds_text(speeds: list) -> str:
    return "/".join(f"{s:g}" for s in speeds)


def over_speed(slot: dict, name: str = "") -> Optional[dict]:
    """The animation's measured speed against the number its data gives, when it averaged more than :data:`OVER_SPEED_RATIO` times it for at least
    :data:`OVER_SPEED_MIN_S` seconds and :data:`OVER_SPEED_MIN_M` metres more than the data gives for that time: ``{"anim", "kind", "data_mps", "measured_mps", "ratio",
    "over_m", "seconds", "basis", "inferred"}``, else None. ``inferred`` is True when the number is a gait read off the clip's name (not a number the data states for it)."""
    d = _data_speed(slot)
    if not d or d["data"] <= 0 or d["seconds"] < OVER_SPEED_MIN_S:
        return None
    ratio = d["measured"] / d["data"]
    over_m = d["metres"] - d["data"] * d["seconds"]
    if ratio <= OVER_SPEED_RATIO or over_m < OVER_SPEED_MIN_M:
        return None
    return {"anim": name, "kind": slot["kind"], "data_mps": round(d["data"], 3), "measured_mps": round(d["measured"], 2), "ratio": round(ratio, 2), "over_m": round(over_m, 1),
            "seconds": round(d["seconds"], 1), "basis": d["basis"], "inferred": d["inferred"]}


def measure(series: list, table: Optional[dict]) -> dict:
    """Measure horizontal travel and speed per animation.

    Keep changes of animation separate and exclude long sample gaps and
    steps classified as teleports. Distinguish motion explained by an
    animation path or explicit speed from gaps in the available data.
    """
    by_kind: dict = defaultdict(float)
    anims: dict = {}
    every: dict = {}                                     # animation -> [metres, seconds, seconds inside an enrage window] over every step of it, standing ones included
    teleports: list = []                                 # the steps faster than TELEPORT_MPS: placements, in no meter
    windows = angry_windows(series, table)
    moved = moving_s = sideways = transition = 0.0
    for (t0, x0, y0, yaw0, a0, _), (t1, x1, y1, yaw1, a1, _) in zip(series, series[1:]):
        dt = t1 - t0
        if dt <= 0 or dt > MAX_STEP_S:
            continue
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist / dt > TELEPORT_MPS:
            teleports.append({"t": round(t0, 2), "m": round(dist, 1), "anim": a0 if a0 == a1 else f"{a0} -> {a1}"})
            continue
        if a0 == a1:
            acc = every.setdefault(a0, [0.0, 0.0, 0.0])
            acc[0] += dist
            acc[1] += dt
            if any(b <= t0 < e for b, e in windows):
                acc[2] += dt
        if dist / dt < MOVING_MPS:
            continue
        if a0 != a1:
            transition += dist                       # the step the animation changed in: it belongs to neither
            moved += dist
            moving_s += dt
            continue
        kind = _kind(table, a0)
        off = _heading_off(dx, dy, yaw0) if yaw0 is not None else None
        side = off is not None and off > OFF_FACING_DEG and kind != "root"
        moved += dist
        moving_s += dt
        by_kind[kind] += dist
        if side:
            sideways += dist
        slot = anims.setdefault(a0, {"m": 0.0, "s": 0.0, "side_m": 0.0, "kind": kind})
        slot["m"] += dist
        slot["s"] += dt
        slot["side_m"] += dist if side else 0.0
    paths: dict = defaultdict(list)
    for anim, seconds, metres in _runs(series):
        if anim in anims and seconds > 0:
            paths[anim].append(metres)
    for name, slot in anims.items():
        entry = table["anims"].get(name.lower()) if table else None
        slot["mean_mps"] = round(slot["m"] / slot["s"], 2) if slot["s"] else 0.0
        slot["root_mps"] = entry["root"] if entry else None
        slot["net_mps"] = entry.get("net", entry["root"]) if entry else None
        slot["path_only"] = bool(entry and entry["root"] >= ROOT_MOTION_MPS and slot["net_mps"] < ROOT_MOTION_MPS)      # net displacement is below the motion threshold
        slot["set_mps"] = entry["set"] if entry else []
        slot["matches"] = gait_matches(table, slot["mean_mps"]) if slot["kind"] in ("none", "nodata") else []
        slot["gait"] = candidate_gait(table, name) if slot["kind"] == "nodata" else None
        runs = paths.get(name, [])
        slot["runs"] = len(runs)
        slot["run_m"] = round(sum(runs) / len(runs), 2) if runs else None
        slot["clip_m"] = round(entry["root"] * entry["dur"], 2) if entry and entry["root"] >= ROOT_MOTION_MPS and entry.get("dur") else None
        slot["clip_net_m"] = round(slot["net_mps"] * entry["dur"], 2) if entry and slot["clip_m"] is not None else None
        every_m, every_s, every_angry = every.get(name, [0.0, 0.0, 0.0])
        slot["all_m"], slot["all_s"], slot["all_angry_s"] = round(every_m, 2), round(every_s, 2), round(every_angry, 2)
        slot["angry_scale"] = ((table or {}).get("angry") or {}).get("scale")
        slot["all_mps"] = round(every_m / every_s, 2) if every_s else 0.0
        for k in ("m", "s", "side_m"):
            slot[k] = round(slot[k], 2)
    over = [o for o in (over_speed(slot, name) for name, slot in anims.items()) if o]
    over.sort(key=lambda o: -o["over_m"])
    return {"moved_m": round(moved, 1), "moving_s": round(moving_s, 1), "transition_m": round(transition, 1),
            "by_kind": {k: round(v, 1) for k, v in by_kind.items()},
            "unaccounted_m": round(by_kind.get("none", 0.0) + by_kind.get("unnamed", 0.0), 1) if table is not None else None,
            "nodata_m": round(by_kind.get("nodata", 0.0) + by_kind.get("noprofile", 0.0), 1),
            "sideways_m": round(sideways, 1), "anims": anims, "over_speed": over,
            "teleports": teleports[:8], "teleport_n": len(teleports), "teleport_m": round(sum(s["m"] for s in teleports), 1)}


def analyse(rows: list, entities: dict, tables: dict) -> dict:
    """Measure recorded movement for each entity using its supplied motion table."""
    out: dict = {}
    for mid, series in monster_series(rows).items():
        entity = entities.get(mid)
        table = tables.get(entity) if entity else None
        result = measure(series, table)
        if result["moved_m"] < MIN_MOVED_M and not result["teleport_n"]:
            continue
        result.update({"entity": entity, "profile": table is not None, "unresolved": table["unresolved"] if table else [], "gaits": table["gaits"] if table else {}})
        out[mid] = result
    return out


def mark_motion(series: dict, mid, t: float, table: Optional[dict] = None) -> Optional[dict]:
    """What one monster was doing at second ``t`` of a hunt: the animation playing, its speed over the second around ``t`` and the angle between that step and the
    way it faced (None when the monster has no rows near ``t``). A placement inside the second (a step faster than :data:`TELEPORT_MPS`) is no walk: the speed is read
    on the side of it the row nearest ``t`` is on, and ``placed_m`` lists the placements' metres (the key is there only when there was one)."""
    rows = series.get(mid) or []
    near = [r for r in rows if abs(r[0] - t) <= 0.5]
    if len(near) < 2:
        return None
    nearest = min(near, key=lambda r: abs(r[0] - t))
    segments, placed = [[near[0]]], []
    for a, b in zip(near, near[1:]):
        step = math.hypot(b[1] - a[1], b[2] - a[2])
        if b[0] > a[0] and step / (b[0] - a[0]) > TELEPORT_MPS:
            placed.append(round(step, 1))
            segments.append([b])
        else:
            segments[-1].append(b)
    own = next(s for s in segments if any(r is nearest for r in s))
    first, last = own[0], own[-1]
    dt = last[0] - first[0]
    dist = math.hypot(last[1] - first[1], last[2] - first[2])
    speed = dist / dt if dt > 0 else 0.0
    off = _heading_off(last[1] - first[1], last[2] - first[2], nearest[3]) if nearest[3] is not None and dist / max(dt, 1e-9) >= MOVING_MPS else None
    out = {"anim": nearest[4], "speed_mps": round(speed, 2), "off_facing_deg": round(off) if off is not None else None, "kind": _kind(table, nearest[4])}
    if placed:
        out["placed_m"] = placed
    return out


def fastest_sustained(results: dict) -> Optional[dict]:
    """Find the fastest average speed for an animation observed for at least one second."""
    best = None
    for mid, r in results.items():
        for name, slot in r["anims"].items():
            if slot["all_s"] >= FASTEST_MIN_S and (best is None or slot["all_mps"] > best["mps"]):
                best = {"mps": slot["all_mps"], "anim": name, "entity": r.get("entity"), "id": mid, "seconds": slot["all_s"]}
    return best


def rate_check(hz: Optional[float], fps: Optional[float] = None, speed_mps: Optional[float] = None, synced: bool = False,
               *, reference_hz: Optional[float] = None) -> Optional[dict]:
    """Estimate worst-case placement lag at constant speed.

    An update period of 1 / hz gives a displacement bound of speed / hz.
    The optional reference rate provides a comparison. This calculation
    leaves interpolation and displayed motion unmeasured.
    """
    if not hz or hz <= 0:
        return None
    fps = fps if fps and fps > 0 else None
    out = {"hz": hz, "fps": fps, "period_ms": round(1000.0 / hz, 1), "per_frame": round(hz / fps, 2) if fps else None,
           "behind": bool(fps) and hz < BEHIND_SHARE * fps, "speed_mps": None, "stale_cm": None, "default_cm": None, "limit_cm": round(STALE_LIMIT_M * 100, 1),
           "over": False, "level": None, "synced": bool(synced)}
    if speed_mps and speed_mps > 0:
        out.update({"speed_mps": speed_mps, "stale_cm": round(speed_mps / hz * 100, 1), "default_cm": round(speed_mps / reference_hz * 100, 1) if reference_hz and reference_hz > 0 else None,
                    "over": speed_mps / hz > STALE_LIMIT_M})
        out["level"] = ("PROBLEM" if out["behind"] and not synced else "WATCH") if out["over"] else None
    return out


def _share(part: Optional[float], whole: float) -> float:
    return (part or 0.0) / whole if whole else 0.0


def is_glide(result: dict) -> bool:
    """Whether a monster's meter shows a glide: metres outside its data (it names no speed for them) that are a real share of what it moved."""
    u = result.get("unaccounted_m")
    return u is not None and u >= MIN_MOVED_M and _share(u, result["moved_m"]) >= GLIDE_WATCH_SHARE


def is_sideways(result: dict) -> bool:
    return result["sideways_m"] >= MIN_MOVED_M and _share(result["sideways_m"], result["moved_m"]) >= GLIDE_WATCH_SHARE


def has_no_data(result: dict) -> bool:
    return result["nodata_m"] >= MIN_MOVED_M


def clip_lines(result: dict, limit: int = 3) -> list:
    """Compare the measured run path with the supplied clip path and net displacement."""
    rows = [(n, s) for n, s in result["anims"].items() if s["kind"] == "root" and s["clip_m"] and s["run_m"] is not None and s["runs"] >= 3]
    rows.sort(key=lambda kv: -kv[1]["m"])
    out = []
    for n, s in rows[:limit]:
        line = f"{n}: {s['runs']} runs of {s['run_m']:g} m on average, the clip's own path is {s['clip_m']:g} m"
        if s.get("clip_net_m") is not None and abs(s["clip_net_m"] - s["clip_m"]) > 0.05 * s["clip_m"]:
            line += f" (its net forward displacement, the net-motion measure, is {s['clip_net_m']:g} m)"
        out.append(line)
    return out
