import unittest

from mho.scaling import (
    HUNT_RANKS, Recipe, ScaleFactors, SoloPolicy, factors_for, scale_monster,
)


class SoloScalingTest(unittest.TestCase):
    def test_solo_values_match_spec(self):
        f = factors_for(1)
        self.assertEqual((f.health, f.damage), (0.40, 0.65))

    def test_scale_monster_math(self):
        hp, dmg = scale_monster(1000, 200, player_count=1)
        self.assertAlmostEqual(hp, 400.0)
        self.assertAlmostEqual(dmg, 130.0)

    def test_clamp_above_table_and_reject_zero(self):
        self.assertEqual(factors_for(99), factors_for(4))  # clamps to max key
        with self.assertRaises(ValueError):
            factors_for(0)

    def test_custom_table(self):
        table = {1: ScaleFactors(0.5, 0.5)}
        hp, dmg = scale_monster(100, 100, 1, table)
        self.assertEqual((hp, dmg), (50.0, 50.0))

    def test_sparse_table_uses_nearest_lower_key(self):
        table = {1: ScaleFactors(0.4, 0.6), 4: ScaleFactors(1.0, 1.0)}
        self.assertEqual(factors_for(2, table), table[1])  # nearest lower, not table[4]
        self.assertEqual(factors_for(3, table), table[1])
        self.assertEqual(factors_for(4, table), table[4])
        self.assertEqual(factors_for(9, table), table[4])  # above max clamps to max


class SoloPolicyTest(unittest.TestCase):
    def test_all_ranks_available(self):
        self.assertEqual(SoloPolicy().available_ranks(), HUNT_RANKS)

    def test_costs_zeroed(self):
        self.assertEqual(SoloPolicy().quest_cost(stamina=50, tickets=1), (0, 0))
        strict = SoloPolicy(ignore_stamina_cost=False, ignore_hunt_tickets=False)
        self.assertEqual(strict.quest_cost(50, 1), (50, 1))

    def test_craft_checks_materials_only(self):
        r = Recipe(item_id=1, materials={100: 2, 101: 1}, license_rank="G-Rank")
        p = SoloPolicy()  # licenses ignored
        self.assertTrue(p.can_craft(r, {100: 5, 101: 1}))
        self.assertFalse(p.can_craft(r, {100: 1, 101: 1}))  # not enough of mat 100

    def test_craft_with_licenses_enforced(self):
        r = Recipe(item_id=1, materials={100: 1}, license_rank="High Rank")
        strict = SoloPolicy(ignore_craft_licenses=False)
        self.assertFalse(strict.can_craft(r, {100: 9}, player_rank="Low Rank"))
        self.assertTrue(strict.can_craft(r, {100: 9}, player_rank="G-Rank"))


if __name__ == "__main__":
    unittest.main()
