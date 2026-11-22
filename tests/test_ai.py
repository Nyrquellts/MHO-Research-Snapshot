import math
import random
import unittest

from mho.ai import AIConfig, MonsterAIManager, MonsterState, STATE_ANIM
from mho.terrain import MapGrid


class FakeMonster:
    def __init__(self, health):
        self.max_health = health
        self.health = health

    @property
    def alive(self):
        return self.health > 0


def _monster(hp=1000):
    return FakeMonster(hp)


class AIManagerTest(unittest.TestCase):
    def setUp(self):
        self.grid = MapGrid.flat_plane(-100, 100, -100, 100, z=5.0)
        self.mgr = MonsterAIManager(self.grid, tick_hz=20.0)

    def test_spawn_assigns_netid_and_clamps_z(self):
        a = self.mgr.spawn(_monster(), 0, 0)
        self.assertGreaterEqual(a.net_id, 1)
        self.assertEqual(a.z, 5.0)                 # clamped to terrain on spawn
        b = self.mgr.spawn(_monster(), 1, 1)
        self.assertEqual(b.net_id, a.net_id + 1)   # monotonic ids

    def test_idle_to_aggro_to_attack(self):
        cfg = AIConfig(aggro_radius=25, attack_radius=4, attack_cooldown=2)
        a = self.mgr.spawn(_monster(), 0, 0, cfg)
        target = (3.0, 0.0)  # within both aggro and attack radius
        s1 = a.tick(0.05, self.grid, target)
        self.assertEqual(s1.state, MonsterState.AGGRO)   # idle -> aggro on sight
        s2 = a.tick(0.05, self.grid, target)
        self.assertEqual(s2.state, MonsterState.ATTACK)  # aggro -> attack in range
        self.assertEqual(s2.anim_hash, STATE_ANIM[MonsterState.ATTACK])

    def test_moves_toward_target_and_stays_on_terrain(self):
        cfg = AIConfig(aggro_radius=50, attack_radius=2, move_speed=6)
        a = self.mgr.spawn(_monster(), 0, 0, cfg)
        target = (40.0, 0.0)  # in aggro range, far from attack range -> must walk
        a.tick(0.05, self.grid, target)  # idle -> aggro
        x_before = a.x
        for _ in range(5):
            snap = a.tick(0.05, self.grid, target)
            self.assertTrue(math.isfinite(snap.z))
            self.assertEqual(snap.z, 5.0)   # terrain clamp holds every tick
        self.assertGreater(a.x, x_before)   # made progress toward the target

    def test_leash_returns_home(self):
        cfg = AIConfig(leash_radius=60)
        a = self.mgr.spawn(_monster(), 0, 0, cfg)
        a.state = MonsterState.AGGRO
        a.x, a.y = 100.0, 0.0                 # dragged beyond leash from home (0,0)
        snap = a.tick(0.05, self.grid, (101.0, 0.0))
        self.assertEqual(snap.state, MonsterState.WANDER)  # disengages

    def test_flinch_interrupts_then_resumes(self):
        cfg = AIConfig(flinch_duration=0.3)
        a = self.mgr.spawn(_monster(), 0, 0, cfg)
        a.state = MonsterState.ATTACK
        a.flinch()
        self.assertEqual(a.state, MonsterState.FLINCH)
        snap = a.tick(1.0, self.grid, (2.0, 0.0))  # dt exceeds flinch_duration
        self.assertEqual(snap.state, MonsterState.AGGRO)   # back to fighting

    def test_death_is_terminal_and_still(self):
        a = self.mgr.spawn(_monster(hp=10), 0, 0)
        a.state = MonsterState.AGGRO
        a.monster.health = 0.0
        snap = a.tick(0.05, self.grid, (2.0, 0.0))
        self.assertEqual(snap.state, MonsterState.DEAD)
        x, y = a.x, a.y
        for _ in range(3):
            snap = a.tick(0.05, self.grid, (2.0, 0.0))
            self.assertEqual(snap.state, MonsterState.DEAD)
        self.assertEqual((a.x, a.y), (x, y))   # no motion when dead

    def test_manager_tick_all_and_target_callback(self):
        a = self.mgr.spawn(_monster(), 0, 0, AIConfig(aggro_radius=25))
        snaps = self.mgr.tick(target_for=lambda ag: (2.0, 0.0))
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0].net_id, a.net_id)

    def test_wander_is_deterministic_with_seed(self):
        cfg = AIConfig(idle_duration=0.0)  # go straight to wander
        a1 = self.mgr.spawn(_monster(), 0, 0, cfg, rng=random.Random(7))
        a2 = self.mgr.spawn(_monster(), 0, 0, cfg, rng=random.Random(7))
        for _ in range(3):
            a1.tick(0.1, self.grid, None)
            a2.tick(0.1, self.grid, None)
        self.assertAlmostEqual(a1.x, a2.x)
        self.assertAlmostEqual(a1.y, a2.y)

    def test_describe_has_state(self):
        a = self.mgr.spawn(_monster(), 0, 0)
        self.assertIn("SPAWN_IDLE", a.describe())


if __name__ == "__main__":
    unittest.main()
