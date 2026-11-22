"""Persistent state for an offline player, with JSON save and load."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Player:
    name: str = "Hunter"
    hr: int = 1                       # hunter rank
    credits: int = 0
    max_hp: float = 150.0
    potions: int = 10                 # each restores `potion_heal`
    potion_heal: float = 50.0
    inventory: dict[int, int] = field(default_factory=dict)   # item_id -> qty
    weapon_name: str = "Starter Blade"
    weapon_attack: float = 45.0       # a viable starter: reliably fells tier-1 monsters
    weapon_element: str = ""
    weapon_element_value: float = 0.0
    weapon_id: int | None = None
    hunts_won: int = 0

    # -- inventory --------------------------------------------------------------
    def add(self, item_id: int, qty: int = 1) -> None:
        self.inventory[item_id] = self.inventory.get(item_id, 0) + qty

    def add_drops(self, drops) -> None:
        for item_id, qty in drops:
            self.add(item_id, qty)

    def have(self, item_id: int) -> int:
        return self.inventory.get(item_id, 0)

    def equip(self, equipment) -> None:
        """Equip a crafted weapon (a :class:`mho.crafting.Equipment`)."""
        self.weapon_id = equipment.item_id
        self.weapon_name = equipment.name
        self.weapon_attack = equipment.attack
        self.weapon_element = equipment.element
        self.weapon_element_value = equipment.element_value

    # -- persistence ------------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["inventory"] = {str(k): v for k, v in self.inventory.items()}   # JSON keys are strings
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Player":
        d = dict(d)
        d["inventory"] = {int(k): int(v) for k, v in d.get("inventory", {}).items()}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "Player":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
