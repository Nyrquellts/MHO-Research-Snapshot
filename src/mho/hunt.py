"""A seeded, headless encounter benchmark for supplied combat and terrain models.

The fixed-tick loop exercises movement, health and status updates, encounter outcomes,
and loot rolls. The demonstration uses a flat grid and synthetic opponents and rewards.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field

from .ai import AIConfig, MonsterAIManager, MonsterState
from .combat import Element, Monster, MotionValue, PhysType
from .scaling import factors_for
from .terrain import MapGrid


@dataclass
class Hunter:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    max_hp: float = 150.0
    hp: float = 150.0
    attack: float = 100.0
    move_speed: float = 7.0          # slightly faster than the monster, so hunts close
    attack_range: float = 3.5
    attack_interval: float = 0.8     # seconds between the hunter's hits
    motion: MotionValue = field(default_factory=lambda: MotionValue("slash", 22, PhysType.CUT))
    target_part: str | None = None   # None -> the monster's first part
    element: Element = Element.NONE
    elemental_attack: float = 0.0
    status_ailment: str = ""         # "poison"|"paralysis"|"sleep" the weapon inflicts, or ""
    status_power: float = 0.0        # build-up applied per hit
    god: bool = False                # Hold HP at max for test scenarios.


@dataclass
class HuntEvent:
    t: float
    kind: str
    detail: str


@dataclass
class HuntResult:
    outcome: str                     # 'victory' | 'capture' | 'defeat' | 'timeout'
    ticks: int
    elapsed: float
    monster_hp: float
    hunter_hp: float
    drops: list[tuple[int, int]]     # (item_id, quantity)
    events: list[HuntEvent]

    def log(self) -> str:
        return "\n".join(f"[{e.t:6.2f}s] {e.kind:12} {e.detail}" for e in self.events)


class HuntSession:
    """One solo hunt from spawn to result."""

    def __init__(self, grid: MapGrid, monster: Monster, hunter: Hunter, *,
                 monster_x: float = 20.0, monster_y: float = 0.0,
                 ai_config: AIConfig | None = None, player_count: int = 1,
                 monster_touch_damage: float = 40.0, tick_hz: float = 20.0,
                 drop_table: list[tuple[int, float, int]] | None = None,
                 boss_drops=None, partbreak_carves: dict | None = None, reward_slots: int = 3,
                 moveset=None, monster_status=None,
                 capture_hp_percent: float = 0.0, capture_drops=None,
                 flinch_threshold: float | None = None,
                 rng: random.Random | None = None):
        self.rng = rng or random.Random(0)
        # Scale supplied moves relative to their median damage multiplier.
        self.moveset = list(moveset) if moveset else []
        if self.moveset:
            mults = sorted(m.damage_mult for m in self.moveset if m.damage_mult)
            self._median_mult = mults[len(mults) // 2] if mults else 1.0
        self.boss_drops = boss_drops                 # mho.rewards.DropTable | None
        self.partbreak_carves = partbreak_carves or {}   # {part_name: DropTable}
        self.reward_slots = reward_slots
        self._broken_parts: list[str] = []
        self.hunter = hunter
        # Own a private copy so scaling/part-break state never leaks back to the caller's
        # monster (reusing one Monster across hunts would otherwise compound the scaling).
        monster = copy.deepcopy(monster)
        # Solo scaling: shrink monster HP and its outgoing damage for one player.
        f = factors_for(player_count)
        monster.max_health *= f.health
        monster.health = monster.max_health
        self.monster_damage = monster_touch_damage * f.damage
        self.flinch_threshold = flinch_threshold
        self.monster_status = monster_status      # mho.status.StatusTracker | None
        self.capture_hp_percent = capture_hp_percent
        self._capture_pool = capture_drops        # mho.rewards.DropTable | None
        self._capturing = False
        self._poison = None                       # dict(remaining, next_t, dmg) | None
        self._immobile_until = 0.0                # monster can't attack before this time
        self.grid = grid
        self.mgr = MonsterAIManager(grid, tick_hz=tick_hz)
        self.agent = self.mgr.spawn(monster, monster_x, monster_y,
                                    ai_config or AIConfig(), rng=self.rng)
        self.target_part = hunter.target_part or next(iter(monster.parts))
        if self.target_part not in monster.parts:
            raise KeyError(f"target_part {self.target_part!r} is not a part of monster "
                           f"{monster.monster_id} — parts are {list(monster.parts)}")
        self.drop_table = drop_table or []
        self.events: list[HuntEvent] = []
        self._t = 0.0
        self._since_attack = hunter.attack_interval  # can strike as soon as in range
        self._prev_state = self.agent.state
        self.hunter.z = grid.get_ground_z(hunter.x, hunter.y)
        self._log("spawn", f"monster net={self.agent.net_id} hp={monster.max_health:.0f} "
                           f"at ({monster_x:.0f},{monster_y:.0f}); hunter atk={hunter.attack:.0f}")

    def _log(self, kind: str, detail: str) -> None:
        self.events.append(HuntEvent(self._t, kind, detail))

    def _dist(self) -> float:
        return ((self.hunter.x - self.agent.x) ** 2 + (self.hunter.y - self.agent.y) ** 2) ** 0.5

    def run(self, max_seconds: float = 120.0) -> HuntResult:
        dt = self.mgr.dt
        monster = self.agent.monster
        max_ticks = int(max_seconds / dt)
        for tick in range(max_ticks):
            self._t = (tick + 1) * dt
            self._since_attack += dt

            # 0) Poison damage-over-time ticks.
            if self._poison and self._t >= self._poison["next_t"]:
                monster.health = max(0.0, monster.health - self._poison["dmg"])
                self._log("poison", f"{self._poison['dmg']:.0f} tick -> monster hp {monster.health:.0f}")
                self._poison["remaining"] -= 1
                self._poison["next_t"] += 1.0
                if self._poison["remaining"] <= 0:
                    self._poison = None
                if not monster.alive:
                    self._log("death", "monster slain (poison)")
                    return self._finish("victory", tick + 1)

            # 1) Hunter approaches or strikes.
            d = self._dist()
            if d > self.hunter.attack_range:
                self._step_hunter_toward(self.agent.x, self.agent.y, dt)
            elif self._since_attack >= self.hunter.attack_interval:
                self._since_attack = 0.0
                r = monster.apply_hit(self.target_part, self.hunter.motion, self.hunter.attack,
                                      element=self.hunter.element,
                                      elemental_attack=self.hunter.elemental_attack,
                                      flinch_threshold=self.flinch_threshold)
                self._log("hit", f"{r.total:6.1f} dmg to {r.part} -> monster hp "
                                 f"{monster.health:.0f}/{monster.max_health:.0f}"
                                 + (" [PART BREAK]" if r.part_broke else "")
                                 + (" [flinch]" if r.flinch and not r.part_broke else ""))
                if r.part_broke:
                    self.agent.flinch()
                    self._broken_parts.append(r.part)
                # status build-up from the weapon
                if self.monster_status and self.hunter.status_ailment:
                    proc = self.monster_status.apply(self.hunter.status_ailment, self.hunter.status_power)
                    if proc:
                        self._apply_proc(proc)
                if r.killed:
                    self._log("death", "monster slain")
                    return self._finish("victory", tick + 1)
                # capture: once weak enough, a trap + tranq ends the hunt alive
                if (self.capture_hp_percent > 0 and monster.alive
                        and monster.health <= monster.max_health * self.capture_hp_percent / 100):
                    self._log("capture", f"monster trapped and captured at {monster.health:.0f} hp "
                                         f"(<= {self.capture_hp_percent:.0f}%)")
                    return self._finish("capture", tick + 1)

            # 2) Monster AI tick (targets the hunter), clamps to terrain.
            snap = self.agent.tick(dt, self.grid, (self.hunter.x, self.hunter.y))
            if snap.state is MonsterState.AGGRO and self._prev_state is MonsterState.SPAWN_IDLE:
                self._log("aggro", "monster noticed the hunter")
            # A fresh commitment to ATTACK lands a blow on the hunter if in range.
            if snap.state is MonsterState.ATTACK and self._prev_state is not MonsterState.ATTACK:
                if self._t < self._immobile_until:
                    pass  # incapacitated (paralysed/asleep) -- can't attack
                elif self._dist() <= self.agent.config.attack_radius + self.hunter.attack_range:
                    dmg, label = self._choose_attack()
                    self._hunter_takes(dmg, label)
                    if self.hunter.hp <= 0:
                        self._log("defeat", "hunter fainted")
                        return self._finish("defeat", tick + 1)
            self._prev_state = snap.state

            # 3) Hunter stays on the terrain surface.
            self.hunter.z = self.grid.get_ground_z(self.hunter.x, self.hunter.y)

        self._log("timeout", f"monster survived with {monster.health:.0f} hp")
        return self._finish("timeout", max_ticks)

    def _step_hunter_toward(self, tx: float, ty: float, dt: float) -> None:
        dx, dy = tx - self.hunter.x, ty - self.hunter.y
        dist = (dx * dx + dy * dy) ** 0.5
        step = self.hunter.move_speed * dt
        if dist <= step or dist == 0:
            self.hunter.x, self.hunter.y = tx, ty
        else:
            self.hunter.x += dx / dist * step
            self.hunter.y += dy / dist * step

    def _choose_attack(self) -> tuple[float, str]:
        """Pick an attack and scale damage by the selected move's relative strength."""
        if not self.moveset:
            return self.monster_damage, ""
        move = self.rng.choice(self.moveset)
        factor = (move.damage_mult / self._median_mult) if move.damage_mult else 1.0
        label = move.name + (f" [{move.element}]" if move.element else "")
        return self.monster_damage * factor, label

    def _apply_proc(self, proc) -> None:
        if proc.kind == "dot":
            if proc.ticks <= 0 or proc.dmg_per_tick <= 0:
                return  # a poison with no ticks/damage does nothing (blank Count/Dmg in data)
            self._poison = {"remaining": proc.ticks, "next_t": self._t + 1.0, "dmg": proc.dmg_per_tick}
            self._log("status", f"{proc.ailment}! {proc.ticks} ticks x {proc.dmg_per_tick:.0f}")
        else:  # immobilize / sleep
            self._immobile_until = self._t + proc.duration
            self._log("status", f"{proc.ailment}! monster incapacitated for {proc.duration:.0f}s")

    def _hunter_takes(self, dmg: float, move: str = "") -> None:
        via = f" with {move}" if move else ""
        if self.hunter.god:
            self.hunter.hp = self.hunter.max_hp
            self._log("guard", f"god mode absorbed {dmg:.0f}{via}")
            return
        self.hunter.hp = max(0.0, self.hunter.hp - dmg)
        self._log("hurt", f"monster hits{via} for {dmg:.0f} -> hunter hp "
                          f"{self.hunter.hp:.0f}/{self.hunter.max_hp:.0f}")

    def _roll_drops(self) -> list[tuple[int, int]]:
        """Return the victory loot as ``[(item_id, qty), ...]``.

        Roll from the supplied reward and part pools. If no victory pool is supplied, use the
        ``drop_table`` of ``(item_id, chance, qty)``.
        """
        drops: list[tuple[int, int]] = []
        pool = self._capture_pool if self._capturing else self.boss_drops
        if pool is not None:
            drops.extend(pool.roll(self.rng, self.reward_slots))
        elif not self._capturing:
            for item_id, chance, qty in self.drop_table:
                if self.rng.random() < chance:
                    drops.append((item_id, qty))
        for part in self._broken_parts:
            table = self.partbreak_carves.get(part)
            if table is not None:
                drops.extend(table.roll(self.rng, 1))
        return drops

    def _finish(self, outcome: str, ticks: int) -> HuntResult:
        self._capturing = outcome == "capture"
        drops = self._roll_drops() if outcome in ("victory", "capture") else []
        if drops:
            self._log("reward", f"carved drops: {drops}")
        return HuntResult(outcome, ticks, self._t, self.agent.monster.health,
                          self.hunter.hp, drops, self.events)


def simulate_solo_hunt(seed: int = 0, **overrides) -> HuntResult:
    """Run the benchmark with a synthetic grid, opponent, and reward pool."""
    from .combat import Hitzone, MonsterPart
    rng = random.Random(seed)
    grid = MapGrid.flat_plane(-100, 100, -100, 100, z=0.0)
    monster = Monster(1, max_health=800, defense=1.0, parts=[
        MonsterPart("Head", Hitzone(cut=65, impact=70, shot=50), break_threshold=150),
        MonsterPart("Body", Hitzone(cut=40, impact=45, shot=35)),
    ])
    hunter = Hunter(target_part="Head")
    session = HuntSession(grid, monster, hunter,
                          drop_table=[(101, 0.9, 1), (102, 0.35, 2)], rng=rng, **overrides)
    return session.run()
