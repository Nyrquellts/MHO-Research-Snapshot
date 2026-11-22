import unittest

from mho.crafting import Recipe, can_craft, craft, craftable_from


class CraftTest(unittest.TestCase):
    def setUp(self):
        self.r = Recipe(10, "Sample Blade", {20: 2, 21: 1}, money=500)

    def test_can_craft(self):
        self.assertTrue(can_craft(self.r, {20: 3, 21: 1}))
        self.assertFalse(can_craft(self.r, {20: 1, 21: 1}))

    def test_craft_consumes_and_yields(self):
        inv = craft(self.r, {20: 2, 21: 2})
        self.assertEqual(inv[20], 0)
        self.assertEqual(inv[21], 1)
        self.assertEqual(inv[10], 1)

    def test_craft_without_materials_raises(self):
        with self.assertRaises(ValueError):
            craft(self.r, {20: 1})

    def test_craftable_from(self):
        recipes = [self.r, Recipe(200, "other", {999: 1})]
        got = craftable_from({20: 2, 21: 1}, recipes)
        self.assertEqual([r.result_id for r in got], [10])


if __name__ == "__main__":
    unittest.main()
