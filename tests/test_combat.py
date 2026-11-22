import unittest

from mho.combat import (
    Hitzone, Monster, MonsterPart, MotionValue, PhysType,
    compute_damage, weakest_part,
)


class WeakestPartTest(unittest.TestCase):
    def test_picks_highest_hitzone_excluding_wholebody(self):
        m = Monster(1, 100, 1.0, [
            MonsterPart("WholeBody", Hitzone(cut=99)),   # excluded despite highest
            MonsterPart("Head", Hitzone(cut=65)),
            MonsterPart("Tail", Hitzone(cut=45)),
        ])
        self.assertEqual(weakest_part(m), "Head")

    def test_wholebody_only_falls_back(self):
        m = Monster(2, 100, 1.0, [MonsterPart("WholeBody", Hitzone(cut=50))])
        self.assertEqual(weakest_part(m), "WholeBody")   # no crash on single WholeBody part

    def test_no_parts_raises(self):
        m = Monster(1, 100, 1.0, [])
        with self.assertRaises(ValueError):
            weakest_part(m)


class DamageFormulaTest(unittest.TestCase):
    def test_matches_pipeline_formula_by_hand(self):
        # raw = MV * atk * (hz/100) / defense
        raw, ele, total = compute_damage(22, 100, 45, 10)
        self.assertAlmostEqual(raw, 22 * 100 * 0.45 / 10)   # 99.0
        self.assertEqual(ele, 0.0)
        self.assertAlmostEqual(total, 99.0)

    def test_weak_point_over_100_and_immune_zero(self):
        weak, _, _ = compute_damage(20, 100, 120, 5)
        full, _, _ = compute_damage(20, 100, 100, 5)
        immune, _, _ = compute_damage(20, 100, 0, 5)
        self.assertGreater(weak, full)
        self.assertEqual(immune, 0.0)

    def test_defense_floor_no_div_by_zero(self):
        raw, _, total = compute_damage(20, 100, 100, 0)  # defense 0 -> floored
        self.assertTrue(raw > 0 and raw == raw)  # finite, not NaN

    def test_elemental_added(self):
        raw, ele, total = compute_damage(10, 100, 100, 10,
                                         elemental_attack=300, element_hitzone_pct=30)
        self.assertAlmostEqual(ele, 300 * 1.0 * 0.30)
        self.assertAlmostEqual(total, raw + ele)


class MonsterCombatTest(unittest.TestCase):
    def _monster(self):
        head = MonsterPart("Head", Hitzone(cut=65, impact=70, shot=50, dragon=25),
                           break_threshold=120)
        tail = MonsterPart("Tail", Hitzone(cut=45, impact=30, shot=40), break_threshold=None)
        return Monster(3, max_health=500, defense=10, parts=[head, tail])

    def test_hit_reduces_hp(self):
        m = self._monster()
        mv = MotionValue("slash", 20, PhysType.CUT)
        r = m.apply_hit("Head", mv, player_attack=100)
        self.assertAlmostEqual(r.total, 20 * 100 * 0.65 / 10)  # 130
        self.assertAlmostEqual(m.health, 500 - 130)
        self.assertFalse(r.killed)

    def test_part_break_flinches(self):
        m = self._monster()
        mv = MotionValue("slash", 20, PhysType.CUT)  # 130 dmg each, threshold 120
        r = m.apply_hit("Head", mv, player_attack=100)
        self.assertTrue(r.part_broke)   # 130 >= 120
        self.assertTrue(r.flinch)
        self.assertTrue(m.parts["Head"].broken)
        r2 = m.apply_hit("Head", mv, player_attack=100)
        self.assertFalse(r2.part_broke)  # already broken, doesn't re-break

    def test_kill_flag_and_floor(self):
        m = self._monster()
        mv = MotionValue("huge", 1000, PhysType.CUT)
        r = m.apply_hit("Head", mv, player_attack=100)
        self.assertTrue(r.killed)
        self.assertEqual(m.health, 0.0)
        self.assertFalse(m.alive)

    def test_unknown_part_raises(self):
        m = self._monster()
        with self.assertRaises(KeyError):
            m.apply_hit("Wing", MotionValue("x", 1), 1)


if __name__ == "__main__":
    unittest.main()
