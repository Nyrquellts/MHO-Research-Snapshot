"""Quest selection and wallet totals for caller-provided quest records."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quest:
    quest_id: int
    name: str
    note: str
    target_monster: int      # the featured monster, or 0
    level: int               # the hunting stage to clear (objective), or 0
    count: int               # objective count
    timeout: int             # seconds (0 = none)
    star: int                # difficulty
    group: int
    can_repeat: bool


def hunt_quests(quests: list[Quest], monster_ids: set[int]) -> list[Quest]:
    """Find quests featuring a monster from the supplied huntable set."""
    return [q for q in quests if q.target_monster in monster_ids]


@dataclass(frozen=True)
class QuestPay:
    """The experience and two currency balances a quest adds."""
    exp: int = 0
    money: int = 0
    bound_money: int = 0

    def __add__(self, other: "QuestPay") -> "QuestPay":
        return QuestPay(self.exp + other.exp, self.money + other.money, self.bound_money + other.bound_money)

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.exp, self.money, self.bound_money)
