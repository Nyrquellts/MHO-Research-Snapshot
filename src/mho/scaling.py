"""Stage 5 -- solo scaling and progression unlocks.

MHO was a group-hunt MMO; a lone hunter needs the fight brought down to one player.
The pipeline directive: when a hunt has exactly one player, multiply monster max health
by 0.40 and monster damage by 0.65. This module expresses that as a small, extensible
scaling table (so 2-3 player scaling can be added later) plus the progression policy
that opens the solo game up: no calendar gates, no stamina/ticket costs, and crafting
gated only on the materials the player actually holds.

All pure functions -- no server, no I/O. The World server calls these when it builds a
hunt instance and when it answers a craft/quest request.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScaleFactors:
    health: float
    damage: float


# Prototype tuning by party size. The solo values reduce health and damage most.
DEFAULT_SCALING: dict[int, ScaleFactors] = {
    1: ScaleFactors(health=0.40, damage=0.65),
    2: ScaleFactors(health=0.70, damage=0.80),
    3: ScaleFactors(health=0.85, damage=0.90),
    4: ScaleFactors(health=1.00, damage=1.00),
}


def factors_for(player_count: int, table: dict[int, ScaleFactors] | None = None) -> ScaleFactors:
    """Return the scale factors for a hunt with ``player_count`` players (>=1).

    Exact match wins. Otherwise the nearest *lower* key is used (so a count above the max
    clamps to the max, and a sparse table like ``{1, 4}`` gives a count of 2 the key-1 factors
    rather than key-4's no-scaling). A count below every key falls back to the smallest key.
    Define every count you care about for exact values.
    """
    if player_count < 1:
        raise ValueError("player_count must be >= 1")
    table = table or DEFAULT_SCALING
    if player_count in table:
        return table[player_count]
    lower = [k for k in table if k <= player_count]
    return table[max(lower)] if lower else table[min(table)]


def scale_monster(max_health: float, base_damage: float, player_count: int,
                  table: dict[int, ScaleFactors] | None = None) -> tuple[float, float]:
    """Return ``(scaled_health, scaled_damage)`` for a monster in a hunt of N players."""
    f = factors_for(player_count, table)
    return max_health * f.health, base_damage * f.damage


# -- progression policy --------------------------------------------------------

# Hunting ranks the solo quest counter offers, with no server-side calendar restriction.
HUNT_RANKS = ("Low Rank", "High Rank", "G-Rank", "Aberrant")


@dataclass(frozen=True)
class Recipe:
    item_id: int
    materials: dict[int, int]      # material_id -> qty required
    license_rank: str | None = None  # normally gates the recipe; ignored in solo policy


@dataclass
class SoloPolicy:
    """The switches that turn the MMO economy into a solo sandbox.

    Defaults match the pipeline: infinite repeatable quests (no stamina/ticket cost),
    all ranks available, and crafting gated only on materials held.
    """
    ignore_time_gates: bool = True
    ignore_stamina_cost: bool = True
    ignore_hunt_tickets: bool = True
    ignore_craft_licenses: bool = True

    def available_ranks(self) -> tuple[str, ...]:
        return HUNT_RANKS if self.ignore_time_gates else ()

    def quest_cost(self, stamina: int, tickets: int) -> tuple[int, int]:
        """Return the ``(stamina, tickets)`` actually deducted for a quest launch."""
        return (0 if self.ignore_stamina_cost else stamina,
                0 if self.ignore_hunt_tickets else tickets)

    def can_craft(self, recipe: Recipe, inventory: dict[int, int], player_rank: str | None = None,
                  rank_order: tuple[str, ...] = HUNT_RANKS) -> bool:
        """True if the player can craft ``recipe`` right now.

        Solo policy checks materials only. With licenses enforced, also requires the
        player to have reached the recipe's license rank.
        """
        if not self.ignore_craft_licenses and recipe.license_rank is not None:
            if player_rank is None:
                return False
            if rank_order.index(player_rank) < rank_order.index(recipe.license_rank):
                return False
        return all(inventory.get(mat, 0) >= qty for mat, qty in recipe.materials.items())
