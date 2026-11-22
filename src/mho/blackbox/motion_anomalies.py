"""Spot steep descents, stalled walks, and airborne stretches in movement samples."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from .glide import TELEPORT_MPS


CLIFF_DROP_M = 5.0
CLIFF_WINDOW_S = 10.0
_TOP_EPS_M = 0.5
WALK_IN_PLACE_S = 2.0
WALK_IN_PLACE_M = 0.5
WALK_WORDS = ("walk", "run", "lame", "sprint")
WALK_TRANSITIONS = ("prepare", "start", "end", "to", "stop")
_CLIP_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_AIR_WORDS = frozenset({"fly", "flying", "hover", "hovering", "air", "inair", "sky", "glide"})


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _teleport_cuts(mon: list[dict]) -> list[int]:
    """For each of one monster's ``mon`` rows (oldest first), the index of the first later row a teleport reaches -- a step faster than
    :data:`glide.TELEPORT_MPS` in three dimensions -- or ``len(mon)`` when none follows."""
    n = len(mon)
    cut = [n] * n
    for m in range(n - 2, -1, -1):
        a, b = mon[m], mon[m + 1]
        dt = float(b["t"]) - float(a["t"])
        far = math.dist(_xyz(a), _xyz(b))
        cut[m] = m + 1 if dt > 0 and far / dt > TELEPORT_MPS else cut[m + 1]
    return cut


def _xyz(r: dict) -> tuple:
    return (_num(r.get("x")) or 0.0, _num(r.get("y")) or 0.0, float(r["z"]))


def cliff_walks(rows: list[dict], drop_m: float = CLIFF_DROP_M, window_s: float = CLIFF_WINDOW_S) -> list[dict]:
    """Find each entity's largest descent within the specified window.

    Exclude position jumps and report the animation names along the descent.
    A large descent may be normal on a slope.
    """
    by_id = defaultdict(list)
    for r in rows:
        if r.get("e") == "mon" and _num(r.get("z")) is not None and _num(r.get("t")) is not None:
            by_id[r.get("id")].append(r)
    out = []
    for mid, mon in by_id.items():
        mon.sort(key=lambda r: r["t"])
        cut = _teleport_cuts(mon)
        best = None
        j = 0
        for i, a in enumerate(mon):
            while j < len(mon) and float(mon[j]["t"]) - float(a["t"]) <= window_s:
                j += 1
            k = min(range(i, min(j, cut[i])), key=lambda n: float(mon[n]["z"]), default=i)
            drop = float(a["z"]) - float(mon[k]["z"])
            if drop >= drop_m and (best is None or drop > best[2]):
                best = (i, k, drop)
        if best is None:
            continue
        i, k, _ = best
        top = float(mon[i]["z"])
        s = max((n for n in range(i, k) if float(mon[n]["z"]) >= top - _TOP_EPS_M), default=i)     # the last row still at the top
        start, low = mon[s], mon[k]
        anims = Counter(str(r.get("anim")) for r in mon[s:k + 1] if r.get("anim") is not None)
        out.append({"monster": mid, "t0": round(float(start["t"]), 1), "t1": round(float(low["t"]), 1), "z0": round(float(start["z"]), 1),
                    "z1": round(float(low["z"]), 1), "drop_m": round(float(start["z"]) - float(low["z"]), 1),
                    "anim": start.get("anim"), "anims": [a for a, _ in anims.most_common(3)],
                    "descent_s": round(float(low["t"]) - float(start["t"]), 1)})
    return sorted(out, key=lambda b: -b["drop_m"])


def _walking(anim) -> bool:
    """Whether a clip is a walk: one of its name's words is a walk word (:data:`WALK_WORDS`) and none says it goes into or out of one
    (:data:`WALK_TRANSITIONS`). Whole words, so Shoot_Drunk, Attack_NormalTrunBack and Flame are not walks."""
    words = {w.lower() for w in _CLIP_WORDS.findall(str(anim or ""))}
    return bool(words & set(WALK_WORDS)) and not words & set(WALK_TRANSITIONS)


def _walking_alive(r: dict) -> bool:
    """Check for a walking sample that still has positive or unknown health."""
    hp = _num(r.get("hp"))
    return _walking(r.get("anim")) and (hp is None or hp > 0)


def walks_in_place(rows: list[dict]) -> list[dict]:
    """Find long walking stretches that cover less than the distance threshold."""
    by = defaultdict(list)
    for r in rows:
        if r.get("e") == "mon" and _num(r.get("t")) is not None and _num(r.get("x")) is not None and _num(r.get("y")) is not None:
            by[r.get("id")].append(r)
    out = []
    for mid, rs in by.items():
        rs.sort(key=lambda r: float(r["t"]))
        first = last = None
        for r in rs + [None]:
            if (r is not None and first is not None and _walking_alive(r)
                    and math.hypot(float(r["x"]) - float(first["x"]), float(r["y"]) - float(first["y"])) <= WALK_IN_PLACE_M):
                last = r
                continue
            if first is not None and float(last["t"]) - float(first["t"]) >= WALK_IN_PLACE_S - 1e-9:
                out.append({"id": mid, "t": round(float(first["t"]), 3), "s": round(float(last["t"]) - float(first["t"]), 3),
                            "at": [round(float(first["x"]), 1), round(float(first["y"]), 1)], "anim": first.get("anim")})
            first = last = r if r is not None and _walking_alive(r) else None
    out.sort(key=lambda w: (-w["s"], w["t"]))
    return out


def clip_words(name) -> list[str]:
    """Split an animation name on separators and camel case."""
    words: list[str] = []
    for run in re.split(r"[^A-Za-z]+", str(name or "")):
        words.extend(w.lower() for w in re.split(r"(?<=[a-z])(?=[A-Z])", run) if w)
    return words


def is_air_clip(name) -> bool:
    """Check for whole words or prefixes associated with flight and hovering."""
    return any(w in _AIR_WORDS or w.startswith("fly") or w.startswith("hover") for w in clip_words(name))


def flight(rows: list[dict]) -> dict:
    """Summarize rise from the first sample of each airborne animation stretch."""
    clips: Counter = Counter()
    open_at: dict = {}
    stretches = []
    for r in rows:
        if r.get("e") != "mon":
            continue
        mid, z = r.get("id"), r.get("z")
        air = is_air_clip(r.get("anim")) and (r.get("hp") is None or r.get("hp") > 0) and isinstance(z, (int, float)) and math.isfinite(z)
        if air:
            clips[str(r.get("anim"))] += 1
            s = open_at.get(mid)
            if s is None:
                open_at[mid] = s = {"id": mid, "t0": r.get("t"), "z0": z, "rise": 0.0, "rows": 0}
                stretches.append(s)
            s["rise"] = max(s["rise"], z - s["z0"])
            s["rows"] += 1
        else:
            open_at.pop(mid, None)
    top = max(stretches, key=lambda s: s["rise"], default=None)
    return {"air_rows": sum(clips.values()), "clips": dict(clips.most_common(8)), "stretches": len(stretches),
            "lifted": len([s for s in stretches if s["rise"] >= 1.0]), "highest": round(top["rise"], 2) if top else 0.0,
            "highest_id": top["id"] if top else None, "highest_t": top["t0"] if top else None}
