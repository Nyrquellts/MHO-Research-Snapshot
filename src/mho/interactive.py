"""A turn-based encounter prototype over caller-supplied combat content.

Call step with a single action for a test, or supply action and output callbacks to play.
The content object supplies a monster, its label, optional status state, capture thresholds,
and reward pools. The prototype has no client or file loaders.
"""
from __future__ import annotations

import copy
import random

from .combat import Element, MotionValue, PhysType, weakest_part
from .scaling import factors_for


def _bar(cur: float, mx: float, width: int = 20) -> str:
    filled = 0 if mx <= 0 else max(0, min(width, round(cur / mx * width)))
    return "[" + "#" * filled + "-" * (width - filled) + f"] {max(0, cur):.0f}/{mx:.0f}"


class InteractiveHunt:
    """One hunt the player fights round by round."""

    def __init__(self, content, player, monster_id: int, *, moveset=None, terrain=None,
                 defense: float = 18.0, player_count: int = 1,
                 monster_touch_damage: float = 40.0, reward_slots: int = 6, seed: int = 0):
        self.content = content
        self.player = player
        self.monster_id = monster_id
        self.rng = random.Random(seed)
        base = content.monster(monster_id)
        if base is None:
            raise KeyError(f"unknown monster {monster_id}")
        self.monster = copy.deepcopy(base)
        self.monster.defense = defense
        f = factors_for(player_count)
        self.monster.max_health *= f.health
        self.monster.health = self.monster.max_health
        self.monster_damage = monster_touch_damage * f.damage

        self.moveset = list(moveset) if moveset else []
        mults = sorted(m.damage_mult for m in self.moveset if m.damage_mult)
        self._median_mult = mults[len(mults) // 2] if mults else 1.0
        self.status = content.status_tracker(monster_id)
        self.capture_pct = content.capture_hp_percent.get(monster_id, 0.0)
        self.reward_slots = reward_slots
        self.terrain = terrain

        self.motion = MotionValue(player.weapon_name, 48, PhysType.CUT)
        self.player_hp = player.max_hp
        self.potions = player.potions
        self.broken: list[str] = []
        self._poison = None
        self._sleep_rounds = 0
        self.round = 0
        self.outcome: str | None = None
        self.drops: list[tuple[int, int]] = []

    # -- state views ------------------------------------------------------------
    @property
    def capturable(self) -> bool:
        return self.capture_pct > 0 and self.monster.alive and \
            self.monster.health <= self.monster.max_health * self.capture_pct / 100

    def parts(self) -> list[str]:
        return [p for p in self.monster.parts if p.lower() != "wholebody"] or list(self.monster.parts)

    def default_part(self) -> str:
        return weakest_part(self.monster)

    def status_lines(self) -> list[str]:
        m = self.monster
        lines = [f"{self.content.name(self.monster_id)}  HP {_bar(m.health, m.max_health)}"
                 + ("  [CAPTURABLE]" if self.capturable else "")]
        broken = ", ".join(f"{p}!" if p in self.broken else p for p in self.parts())
        lines.append(f"  parts: {broken}")
        lines.append(f"You  HP {_bar(self.player_hp, self.player.max_hp)}   potions x{self.potions}"
                     f"   weapon: {self.player.weapon_name} (atk {self.player.weapon_attack:.0f}"
                     + (f", {self.player.weapon_element_value:.0f} {self.player.weapon_element}"
                        if self.player.weapon_element else "") + ")")
        return lines

    # -- one round --------------------------------------------------------------
    def step(self, action) -> list[str]:
        """Resolve one round. ``action`` is ('attack', part) | ('potion',) | ('capture',) |
        ('flee',). Returns log lines; sets ``self.outcome`` when the hunt ends.

        Robust to garbage: a malformed or unknown action wastes the round (the monster still
        acts) rather than raising -- so a fuzzer can throw anything at it."""
        if self.outcome is not None:
            return []
        self.round += 1
        log: list[str] = []
        kind = action[0] if isinstance(action, (tuple, list)) and action else None

        # poison damage-over-time on the monster
        if self._poison:
            self.monster.health = max(0.0, self.monster.health - self._poison["dmg"])
            log.append(f"  poison saps {self._poison['dmg']:.0f} ({self.content.name(self.monster_id)} "
                       f"{self.monster.health:.0f} HP)")
            self._poison["ticks"] -= 1
            if self._poison["ticks"] <= 0:
                self._poison = None
            if not self.monster.alive:
                return log + self._win("victory", "succumbs to poison")

        if kind == "attack":
            requested = action[1] if len(action) > 1 else None
            part = requested if isinstance(requested, str) and requested in self.monster.parts else self.default_part()
            r = self.monster.apply_hit(part, self.motion, self.player.weapon_attack,
                                       element=Element.from_name(self.player.weapon_element),
                                       elemental_attack=self.player.weapon_element_value)
            log.append(f"  you hit {part} for {r.total:.0f}"
                       + (f" (+{r.elemental:.0f} {self.player.weapon_element})" if r.elemental else "")
                       + (" — PART BREAK!" if r.part_broke else ""))
            if r.part_broke:
                self.broken.append(part)
            if not self.monster.alive:
                return log + self._win("victory", "is slain")
        elif kind == "potion":
            if self.potions <= 0:
                log.append("  no potions left!")
            else:
                self.potions -= 1
                self.player_hp = min(self.player.max_hp, self.player_hp + self.player.potion_heal)
                log.append(f"  you drink a potion (+{self.player.potion_heal:.0f} → {self.player_hp:.0f} HP)")
        elif kind == "capture":
            if self.capturable:
                return log + self._win("capture", "is trapped and captured")
            log.append("  not weak enough to capture yet.")
        elif kind == "flee":
            self.outcome = "fled"
            return log + ["  you flee the hunt."]
        else:
            log.append(f"  (unknown action {kind})")

        # monster's turn (asleep monsters skip)
        if self._sleep_rounds > 0:
            self._sleep_rounds -= 1
            log.append(f"  {self.content.name(self.monster_id)} is asleep.")
        else:
            dmg, move = self._monster_attack()
            self.player_hp = max(0.0, self.player_hp - dmg)
            log.append(f"  {self.content.name(self.monster_id)} uses {move} for {dmg:.0f} "
                       f"(you {self.player_hp:.0f} HP)")
            if self.player_hp <= 0:
                self.outcome = "defeat"
                return log + ["  you have fainted..."]
        return log

    def _monster_attack(self) -> tuple[float, str]:
        if not self.moveset:
            return self.monster_damage, "a body slam"
        m = self.rng.choice(self.moveset)
        factor = (m.damage_mult / self._median_mult) if m.damage_mult else 1.0
        return self.monster_damage * factor, m.name + (f" [{m.element}]" if m.element else "")

    def _win(self, outcome: str, how: str) -> list[str]:
        self.outcome = outcome
        pool = self.content.capture_drops.get(self.monster_id) if outcome == "capture" \
            else self.content.boss_drops.get(self.monster_id)
        if pool is not None:
            self.drops.extend(pool.roll(self.rng, self.reward_slots))
        for part in self.broken:
            carve = self.content.carves_for(self.monster_id).get(part)
            if carve is not None:
                self.drops.extend(carve.roll(self.rng, 1))
        return [f"  {self.content.name(self.monster_id)} {how}!"]

    def play(self, get_action, emit, *, max_rounds: int = 100_000) -> str:
        """Drive the hunt: ``get_action(self) -> action`` supplies each round's action, ``emit(str)``
        prints. Returns the outcome. Used by the console front-end and by scripted tests.

        ``max_rounds`` is a safety valve so a monster that can neither be killed nor kill (bad
        data) can't hang the loop forever -- it aborts the hunt instead."""
        emit(f"\n=== HUNT: {self.content.name(self.monster_id)} "
             f"(HP {self.monster.max_health:.0f}) ===")
        while self.outcome is None:
            if self.round >= max_rounds:
                self.outcome = "aborted"
                emit("  (hunt aborted: round limit reached)")
                break
            for line in self.status_lines():
                emit(line)
            for line in self.step(get_action(self)):
                emit(line)
        emit(f"\n--- {self.outcome.upper()} ---")
        if self.drops:
            emit("carved: " + self.content.name_drops(self.drops))
        return self.outcome
