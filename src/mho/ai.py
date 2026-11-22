"""Stage 3 -- server-authoritative monster locomotion and AI tick loop.

A ``MonsterAgent`` is one monster's spatial + behavioural state. ``MonsterAIManager``
owns all agents and steps them at a fixed rate (default 20 Hz). Every tick, for every
live agent:

1. the state machine advances (Spawn/Idle -> Wander -> Aggro -> Attack -> Flinch -> Dead);
2. locomotion moves the agent and **clamps it to the terrain**: ``z = grid.get_ground_z(x, y)``
   so a monster can never fall through the world or float;
3. a :class:`Snapshot` (position, heading, state, animation hash, health) is produced for
   the caller to consume.

Design goals that make this testable with no game running:

* Deterministic: time is passed in as ``dt`` (a fake clock), wander points come from an
  injected ``random.Random``, and the aggro target is passed in each tick (the server
  supplies the nearest player). Nothing reads the wall clock or the network.
* The caller owns health and parts. An agent enters its terminal state on the next
  tick after its monster dies. Calling flinch interrupts an attack.

Each state has a synthetic animation identifier so consumers can test snapshots.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol


class Monster(Protocol):
    """The health state the caller provides to a locomotion agent."""

    @property
    def alive(self) -> bool: ...

    @property
    def health(self) -> float: ...

    @property
    def max_health(self) -> float: ...


class MonsterState(IntEnum):
    SPAWN_IDLE = 0
    WANDER = 1
    AGGRO = 2
    ATTACK = 3
    FLINCH = 4
    DEAD = 5


# Synthetic identifiers for the reference model.
STATE_ANIM: dict[MonsterState, int] = {
    MonsterState.SPAWN_IDLE: 0x1000,
    MonsterState.WANDER: 0x1001,
    MonsterState.AGGRO: 0x1002,
    MonsterState.ATTACK: 0x1003,
    MonsterState.FLINCH: 0x1004,
    MonsterState.DEAD: 0x1005,
}


@dataclass
class AIConfig:
    """Tunable behaviour radii (world units) and durations (seconds)."""
    aggro_radius: float = 25.0
    attack_radius: float = 4.0
    leash_radius: float = 60.0        # distance from home before the monster disengages
    move_speed: float = 6.0           # units / second
    turn_rate: float = math.pi        # radians / second toward the desired heading
    idle_duration: float = 2.0
    wander_radius: float = 12.0
    attack_duration: float = 1.2
    attack_cooldown: float = 2.0
    flinch_duration: float = 0.8


@dataclass
class Snapshot:
    net_id: int
    x: float
    y: float
    z: float
    heading: float
    state: MonsterState
    anim_hash: int
    health: float
    target_distance: float | None = None


def _wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _turn_toward(current: float, desired: float, max_step: float) -> float:
    delta = _wrap_angle(desired - current)
    if abs(delta) <= max_step:
        return _wrap_angle(desired)
    return _wrap_angle(current + math.copysign(max_step, delta))


class MonsterAgent:
    """One monster's locomotion + behaviour state."""

    def __init__(self, net_id: int, monster: Monster, x: float, y: float,
                 config: AIConfig | None = None, heading: float = 0.0,
                 rng: random.Random | None = None):
        if net_id < 1:
            raise ValueError("net_id must be >= 1")
        self.net_id = net_id
        self.monster = monster
        self.x = float(x)
        self.y = float(y)
        self.z = 0.0
        self.home_x = float(x)
        self.home_y = float(y)
        self.heading = float(heading)
        self.config = config or AIConfig()
        self.rng = rng or random.Random()
        self.state = MonsterState.SPAWN_IDLE
        self._timer = 0.0            # time spent in the current timed sub-behaviour
        self._cooldown = 0.0         # remaining attack cooldown
        self._wander_target: tuple[float, float] | None = None
        self._death_emitted = False

    # -- external events ---------------------------------------------------------

    def flinch(self) -> None:
        """Interrupt whatever the monster is doing and enter FLINCH (called on part break)."""
        if self.state is not MonsterState.DEAD:
            self.state = MonsterState.FLINCH
            self._timer = 0.0

    # -- helpers -----------------------------------------------------------------

    def _dist_to(self, px: float, py: float) -> float:
        return math.hypot(px - self.x, py - self.y)

    def _dist_home(self) -> float:
        return math.hypot(self.x - self.home_x, self.y - self.home_y)

    def _move_toward(self, tx: float, ty: float, dt: float) -> None:
        desired = math.atan2(ty - self.y, tx - self.x)
        self.heading = _turn_toward(self.heading, desired, self.config.turn_rate * dt)
        step = self.config.move_speed * dt
        d = self._dist_to(tx, ty)
        if d <= step or d == 0.0:
            self.x, self.y = tx, ty
        else:
            self.x += math.cos(self.heading) * step
            self.y += math.sin(self.heading) * step

    def _pick_wander(self) -> tuple[float, float]:
        ang = self.rng.uniform(-math.pi, math.pi)
        r = self.rng.uniform(0.0, self.config.wander_radius)
        return self.home_x + math.cos(ang) * r, self.home_y + math.sin(ang) * r

    # -- the tick ----------------------------------------------------------------

    def tick(self, dt: float, grid, target: tuple[float, float] | None) -> Snapshot:
        """Advance one step. ``grid`` is a :class:`mho.terrain.MapGrid`; ``target`` is the
        nearest player's (x, y) or ``None``. Returns the broadcast snapshot."""
        if dt <= 0:
            raise ValueError("dt must be positive")
        self._cooldown = max(0.0, self._cooldown - dt)
        cfg = self.config

        # Death dominates every other transition.
        if not self.monster.alive:
            self.state = MonsterState.DEAD

        tdist = self._dist_to(*target) if target is not None else None

        if self.state is MonsterState.DEAD:
            pass  # terminal; no motion

        elif self.state is MonsterState.FLINCH:
            self._timer += dt
            if self._timer >= cfg.flinch_duration:
                self._timer = 0.0
                self.state = MonsterState.AGGRO if target is not None else MonsterState.SPAWN_IDLE

        elif self.state is MonsterState.ATTACK:
            self._timer += dt
            if self._timer >= cfg.attack_duration:
                self._timer = 0.0
                self._cooldown = cfg.attack_cooldown
                self.state = MonsterState.AGGRO if target is not None else MonsterState.WANDER

        elif self.state is MonsterState.SPAWN_IDLE:
            self._timer += dt
            if target is not None and tdist <= cfg.aggro_radius:
                self.state = MonsterState.AGGRO
                self._timer = 0.0
            elif self._timer >= cfg.idle_duration:
                self._timer = 0.0
                self._wander_target = self._pick_wander()
                self.state = MonsterState.WANDER

        elif self.state is MonsterState.WANDER:
            if target is not None and tdist <= cfg.aggro_radius:
                self.state = MonsterState.AGGRO
            else:
                if self._wander_target is None:
                    self._wander_target = self._pick_wander()
                self._move_toward(*self._wander_target, dt)
                if self._dist_to(*self._wander_target) < 0.5:
                    self._wander_target = None
                    self.state = MonsterState.SPAWN_IDLE
                    self._timer = 0.0

        elif self.state is MonsterState.AGGRO:
            if target is None or self._dist_home() > cfg.leash_radius:
                self.state = MonsterState.WANDER      # leash: give up and head home
                self._wander_target = (self.home_x, self.home_y)
            elif tdist <= cfg.attack_radius and self._cooldown <= 0.0:
                self.state = MonsterState.ATTACK
                self._timer = 0.0
                # face the target at the moment of commitment
                self.heading = math.atan2(target[1] - self.y, target[0] - self.x)
            else:
                self._move_toward(*target, dt)

        # Locomotion clamp: every tick, snap to the terrain surface.
        self.z = grid.get_ground_z(self.x, self.y)

        if self.state is MonsterState.DEAD:
            self._death_emitted = True

        return Snapshot(
            net_id=self.net_id, x=self.x, y=self.y, z=self.z, heading=self.heading,
            state=self.state, anim_hash=STATE_ANIM[self.state],
            health=self.monster.health, target_distance=tdist,
        )

    def describe(self) -> str:
        """Human-readable summary of the agent's state."""
        return (f"net={self.net_id} state={self.state.name} hp={self.monster.health:.0f}/"
                f"{self.monster.max_health:.0f} pos=({self.x:.1f},{self.y:.1f},{self.z:.1f}) "
                f"heading={math.degrees(self.heading):.0f}deg")


class MonsterAIManager:
    """Owns all live agents and steps them at a fixed rate. NetIDs start at 1."""

    def __init__(self, grid, tick_hz: float = 20.0):
        self.grid = grid
        self.tick_hz = tick_hz
        self.dt = 1.0 / tick_hz
        self.agents: dict[int, MonsterAgent] = {}
        self._next_net_id = 1

    def spawn(self, monster: Monster, x: float, y: float, config: AIConfig | None = None,
              rng: random.Random | None = None) -> MonsterAgent:
        net_id = self._next_net_id
        self._next_net_id += 1
        agent = MonsterAgent(net_id, monster, x, y, config, rng=rng)
        agent.z = self.grid.get_ground_z(x, y)
        self.agents[net_id] = agent
        return agent

    def tick(self, target_for=None) -> list[Snapshot]:
        """Step every agent once. ``target_for(agent) -> (x, y) | None`` supplies each
        agent's current aggro target (the server passes the nearest player)."""
        snaps = []
        for agent in self.agents.values():
            target = target_for(agent) if target_for else None
            snaps.append(agent.tick(self.dt, self.grid, target))
        return snaps
