import random
import unittest

from mho.combat import Hitzone, Monster, MonsterPart
from mho.hunt import Hunter, HuntSession, simulate_solo_hunt
from mho.terrain import MapGrid


class HuntTest(unittest.TestCase):
    def test_solo_hunt_reaches_victory(self):
        r = simulate_solo_hunt(seed=1)
        self.assertEqual(r.outcome, "victory")
        self.assertEqual(r.monster_hp, 0.0)
        kinds = {e.kind for e in r.events}
        self.assertIn("hit", kinds)
        self.assertIn("death", kinds)

    def test_deterministic(self):
        a = simulate_solo_hunt(seed=5)
        b = simulate_solo_hunt(seed=5)
        self.assertEqual((a.outcome, a.ticks), (b.outcome, b.ticks))
        self.assertEqual(a.drops, b.drops)

    def test_solo_scaling_applied(self):
        grid = MapGrid.flat_plane(-50, 50, -50, 50, z=0.0)
        monster = Monster(1, max_health=1000, defense=1.0, parts=[MonsterPart("Body", Hitzone())])
        s = HuntSession(grid, monster, Hunter(), player_count=1)
        self.assertAlmostEqual(s.agent.monster.max_health, 400.0)  # 1000 * 0.40

    def test_caller_monster_not_mutated(self):
        # Reusing a monster across hunts must not compound scaling / part state.
        grid = MapGrid.flat_plane(-50, 50, -50, 50, z=0.0)
        monster = Monster(1, max_health=1000, defense=1.0,
                          parts=[MonsterPart("Head", Hitzone(), break_threshold=10)])
        for _ in range(3):
            HuntSession(grid, monster, Hunter(), player_count=1).run(max_seconds=5)
        self.assertEqual(monster.max_health, 1000)     # unchanged
        self.assertEqual(monster.health, 1000)
        self.assertFalse(monster.parts["Head"].broken)

    def test_part_break_logged(self):
        grid = MapGrid.flat_plane(-50, 50, -50, 50, z=0.0)
        monster = Monster(1, max_health=5000, defense=1.0, parts=[
            MonsterPart("Head", Hitzone(cut=100), break_threshold=50),  # breaks on first hit
        ])
        hunter = Hunter(target_part="Head", attack=100)
        r = HuntSession(grid, monster, hunter, monster_x=6, player_count=4).run(max_seconds=30)
        self.assertTrue(any("PART BREAK" in e.detail for e in r.events))

    def test_capture_outcome_and_drops(self):
        from mho.rewards import DropEntry, DropTable
        grid = MapGrid.flat_plane(-50, 50, -50, 50, z=0.0)
        monster = Monster(1, max_health=400, defense=1.0, parts=[MonsterPart("Body", Hitzone(cut=100))])
        cap = DropTable([DropEntry(201, 1, 1, 100)])
        hunter = Hunter(target_part="Body", attack=1, god=True, max_hp=200)  # small hits land in the capture window
        r = HuntSession(grid, monster, hunter, monster_x=5, player_count=4,
                        capture_hp_percent=15, capture_drops=cap,
                        rng=random.Random(1)).run(max_seconds=60)
        self.assertEqual(r.outcome, "capture")
        self.assertGreater(r.monster_hp, 0)               # captured alive
        self.assertLessEqual(r.monster_hp, 400 * 0.15)    # at/under threshold (post-scale)
        self.assertIn((201, 1), r.drops)

    def test_poison_deals_damage_over_time(self):
        from mho.status import Ailment, StatusTracker
        grid = MapGrid.flat_plane(-50, 50, -50, 50, z=0.0)
        monster = Monster(1, max_health=200, defense=1.0, parts=[MonsterPart("Body", Hitzone(cut=100))])
        tracker = StatusTracker({"poison": Ailment("poison", 50, 50, 500, 20, 3, 0)})
        hunter = Hunter(target_part="Body", attack=0.5, god=True, max_hp=200,
                        status_ailment="poison", status_power=100)  # weak hits so poison ticks land first
        r = HuntSession(grid, monster, hunter, monster_x=5, player_count=4,
                        monster_status=tracker, rng=random.Random(2)).run(max_seconds=60)
        kinds = [e.kind for e in r.events]
        self.assertIn("status", kinds)                    # poison proc logged
        self.assertIn("poison", kinds)                    # DoT ticks logged

    def test_god_mode_never_dies(self):
        grid = MapGrid.flat_plane(-50, 50, -50, 50, z=0.0)
        monster = Monster(1, max_health=400, defense=1.0, parts=[MonsterPart("Body", Hitzone())])
        # Weak hunter (fight lasts) + huge monster damage + god on.
        hunter = Hunter(target_part="Body", attack=1.0, god=True, max_hp=100, hp=100)
        r = HuntSession(grid, monster, hunter, monster_x=5, player_count=4,
                        monster_touch_damage=1000, rng=random.Random(3)).run(max_seconds=40)
        self.assertEqual(r.hunter_hp, 100.0)         # frozen at max
        self.assertNotEqual(r.outcome, "defeat")
        self.assertTrue(any(e.kind == "guard" for e in r.events))  # monster did land hits

    def test_bad_target_part_raises_clearly(self):
        grid = MapGrid.flat_plane(-50, 50, -50, 50, z=0.0)
        monster = Monster(1, max_health=100, defense=1.0, parts=[MonsterPart("Body", Hitzone())])
        with self.assertRaises(KeyError):
            HuntSession(grid, monster, Hunter(target_part="Typo"))


if __name__ == "__main__":
    unittest.main()
