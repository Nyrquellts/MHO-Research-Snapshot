"""Configurable prototype for hitzone damage and breakable parts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PhysType(Enum):
    """Which physical hitzone column a weapon hit reads."""
    CUT = "cut"
    IMPACT = "impact"
    SHOT = "shot"


class Element(Enum):
    NONE = "none"
    FIRE = "fire"
    WATER = "water"
    THUNDER = "thunder"
    ICE = "ice"
    DRAGON = "dragon"

    @classmethod
    def from_name(cls, name: str) -> "Element":
        """Map a table's element string ('fire', 'dragon', '') to an Element (default NONE)."""
        try:
            return cls((name or "none").lower())
        except ValueError:
            return cls.NONE


@dataclass(frozen=True)
class Hitzone:
    """Per-part damage-taken multipliers, as percentages (100 == full damage).

    A value of 45 means the part takes 45% of raw damage there. Values above 100 (weak points) and 0 (immune) are both legal.
    """
    cut: float = 100.0
    impact: float = 100.0
    shot: float = 100.0
    fire: float = 0.0
    water: float = 0.0
    thunder: float = 0.0
    ice: float = 0.0
    dragon: float = 0.0

    def phys(self, t: PhysType) -> float:
        return getattr(self, t.value)

    def elem(self, e: Element) -> float:
        return 0.0 if e is Element.NONE else getattr(self, e.value)


@dataclass
class MonsterPart:
    """A breakable part: its hitzone, the accumulated damage, and its break threshold."""
    name: str
    hitzone: Hitzone
    break_threshold: float | None = None  # None == not breakable
    accumulated: float = 0.0
    broken: bool = False


@dataclass(frozen=True)
class MotionValue:
    """A resolved weapon motion: its physical MV, damage type, and element scaling."""
    name: str
    value: float                 # motion value (percent-style, e.g. 22 for a slash)
    phys_type: PhysType = PhysType.CUT
    element_modifier: float = 1.0  # fraction of the weapon's element applied by this move


@dataclass
class DamageResult:
    raw: float
    elemental: float
    total: float
    part: str
    part_broke: bool = False
    flinch: bool = False
    killed: bool = False


def compute_damage(
    motion_value: float,
    player_attack: float,
    hitzone_pct: float,
    monster_defense: float,
    *,
    elemental_attack: float = 0.0,
    element_hitzone_pct: float = 0.0,
    element_modifier: float = 1.0,
    defense_floor: float = 1.0,
) -> tuple[float, float, float]:
    """Return ``(raw, elemental, total)`` for one hit.

    ``monster_defense`` is a divisor; it is
    floored at ``defense_floor`` so a zero/negative table value can never produce
    ``inf``/``NaN`` inside the tick.
    """
    defense = monster_defense if monster_defense > defense_floor else defense_floor
    raw = (motion_value * player_attack * (hitzone_pct / 100.0)) / defense
    elemental = elemental_attack * element_modifier * (element_hitzone_pct / 100.0)
    if raw < 0.0:
        raw = 0.0
    if elemental < 0.0:
        elemental = 0.0
    return raw, elemental, raw + elemental


def weakest_part(monster, phys: PhysType | str = PhysType.CUT) -> str:
    """The part that takes the most damage of type ``phys`` (the weak point to target).

    Excludes ``WholeBody`` when the monster has real parts, but falls back to it (or the first
    part) when a monster has only a whole-body hitzone.
    """
    t = phys if isinstance(phys, PhysType) else PhysType(phys)
    parts = monster.parts
    if not parts:
        raise ValueError(f"monster {getattr(monster, 'monster_id', '?')} has no parts")
    candidates = [n for n in parts if n.lower() != "wholebody"] or list(parts)
    return max(candidates, key=lambda n: parts[n].hitzone.phys(t))


class Monster:
    """Minimal combat state for a monster: HP and its breakable parts.

    Locomotion and the state machine are separate in mho.ai.
    """

    def __init__(self, monster_id: int, max_health: float, defense: float, parts: list[MonsterPart]):
        self.monster_id = monster_id
        self.max_health = float(max_health)
        self.health = float(max_health)
        self.defense = float(defense)
        self.parts = {p.name: p for p in parts}

    @property
    def alive(self) -> bool:
        return self.health > 0.0

    def apply_hit(
        self,
        part_name: str,
        motion: MotionValue,
        player_attack: float,
        *,
        element: Element = Element.NONE,
        elemental_attack: float = 0.0,
        flinch_threshold: float | None = None,
    ) -> DamageResult:
        """Resolve one landed hit against ``part_name`` and mutate monster state.

        A part break always flinches. A single hit whose total meets ``flinch_threshold``
        also flinches. Returns the full damage result.
        """
        if part_name not in self.parts:
            raise KeyError(f"unknown part {part_name!r}")
        part = self.parts[part_name]
        hz = part.hitzone
        raw, elemental, total = compute_damage(
            motion.value,
            player_attack,
            hz.phys(motion.phys_type),
            self.defense,
            elemental_attack=elemental_attack,
            element_hitzone_pct=hz.elem(element),
            element_modifier=motion.element_modifier,
        )

        was_alive = self.alive
        self.health = max(0.0, self.health - total)

        part_broke = False
        if part.break_threshold is not None and not part.broken:
            part.accumulated += total
            if part.accumulated >= part.break_threshold:
                part.broken = True
                part_broke = True

        flinch = part_broke or (flinch_threshold is not None and total >= flinch_threshold)
        killed = was_alive and not self.alive
        return DamageResult(raw, elemental, total, part_name, part_broke, flinch, killed)
