"""Recipe and equipment models for an offline inventory prototype."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    result_id: int
    name: str
    materials: dict[int, int]         # material item_id -> quantity
    money: int = 0
    result_qty: int = 1


@dataclass(frozen=True)
class Equipment:
    item_id: int
    name: str
    weapon_type: str
    attack: float
    defense: float = 0.0
    element: str = ""
    element_value: float = 0.0
    rarity: int = 1


def can_craft(recipe: Recipe, inventory: dict[int, int]) -> bool:
    """True if the inventory holds every material the recipe needs."""
    return all(inventory.get(mat, 0) >= qty for mat, qty in recipe.materials.items())


def craft(recipe: Recipe, inventory: dict[int, int]) -> dict[int, int]:
    """Return a new inventory with the recipe's materials consumed and its result added.
    Raises ``ValueError`` if the materials aren't available."""
    if not can_craft(recipe, inventory):
        raise ValueError(f"missing materials for {recipe.name}")
    inv = dict(inventory)
    for mat, qty in recipe.materials.items():
        inv[mat] -= qty
    inv[recipe.result_id] = inv.get(recipe.result_id, 0) + recipe.result_qty
    return inv


def craftable_from(inventory: dict[int, int], recipes: list[Recipe]) -> list[Recipe]:
    """Every recipe the inventory can currently make."""
    return [r for r in recipes if can_craft(r, inventory)]
