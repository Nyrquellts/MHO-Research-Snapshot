"""Seedable weighted reward rolls over caller-provided item pools."""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DropEntry:
    item_id: int
    amount_min: int
    amount_max: int
    weight: float = 1.0

    def roll_amount(self, rng: random.Random) -> int:
        return rng.randint(self.amount_min, max(self.amount_min, self.amount_max))


@dataclass
class DropTable:
    entries: list[DropEntry] = field(default_factory=list)

    def roll(self, rng: random.Random, slots: int = 3) -> list[tuple[int, int]]:
        """Weighted picks (with replacement) filling ``slots`` reward boxes -> [(item_id, qty)]."""
        pool = [e for e in self.entries if e.weight > 0]
        if not pool:
            return []
        total = sum(e.weight for e in pool)
        out: list[tuple[int, int]] = []
        for _ in range(slots):
            t = rng.random() * total
            acc = 0.0
            for e in pool:
                acc += e.weight
                if t < acc:
                    out.append((e.item_id, e.roll_amount(rng)))
                    break
        return out
