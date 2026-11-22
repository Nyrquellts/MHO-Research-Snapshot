"""Point thresholds and loadout selection from supplied equipment records."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class SkillTier:
    points: int
    name: str
    effect: str


@dataclass
class EquipSkill:
    group_id: str
    group_name: str
    tiers: list[SkillTier] = field(default_factory=list)   # positive tiers, ascending by points

    def level_for(self, points: int) -> int:
        lvl = 0
        for i, t in enumerate(self.tiers):
            if points >= t.points:
                lvl = i + 1
        return lvl


@dataclass
class ArmorPiece:
    item_id: int
    name: str
    slot: int
    defense: float
    set_id: str
    points: dict[str, int] = field(default_factory=dict)   # group_id -> points (may be negative)


def resolve_skills(points: dict[str, int], catalog: dict[str, EquipSkill]) -> dict[str, tuple[int, str]]:
    """{group_id: (level, skill_name)} for every group with a positive active level."""
    out: dict[str, tuple[int, str]] = {}
    for gid, pts in points.items():
        sk = catalog.get(gid)
        if sk is None or not sk.tiers:
            continue
        lvl = sk.level_for(pts)
        if lvl > 0:
            out[gid] = (lvl, sk.tiers[lvl - 1].name)
    return out


@dataclass
class Loadout:
    pieces: list[ArmorPiece]
    points: dict[str, int]
    skills: dict[str, tuple[int, str]]
    total_defense: float


def assemble_loadout(
    armor: dict[int, ArmorPiece],
    catalog: dict[str, EquipSkill],
    *,
    slots: Sequence[int],
    preferred_groups: Sequence[str],
    tiebreak_group: str,
) -> Loadout:
    """Greedily pick one piece per slot, favoring the supplied skill groups."""
    def preference(piece: ArmorPiece) -> tuple[int, int, float]:
        preferred = sum(piece.points.get(group, 0) for group in preferred_groups)
        return preferred, piece.points.get(tiebreak_group, 0), piece.defense

    chosen: list[ArmorPiece] = []
    for slot in slots:
        candidates = [piece for piece in armor.values() if piece.slot == slot]
        if candidates:
            chosen.append(max(candidates, key=preference))

    points: dict[str, int] = {}
    for piece in chosen:
        for group, value in piece.points.items():
            points[group] = points.get(group, 0) + value

    return Loadout(
        pieces=chosen,
        points=points,
        skills=resolve_skills(points, catalog),
        total_defense=sum(piece.defense for piece in chosen),
    )
