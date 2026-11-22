import os
import tempfile
import unittest

from mho.crafting import Equipment
from mho.player import Player


class PlayerTest(unittest.TestCase):
    def test_inventory_and_drops(self):
        p = Player()
        p.add(100, 2)
        p.add_drops([(100, 1), (200, 3)])
        self.assertEqual(p.have(100), 3)
        self.assertEqual(p.have(200), 3)
        self.assertEqual(p.have(999), 0)

    def test_equip(self):
        p = Player()
        p.equip(Equipment(7, "Sample Sword", "sword", attack=123, element="dragon", element_value=120))
        self.assertEqual(p.weapon_name, "Sample Sword")
        self.assertEqual(p.weapon_attack, 123)
        self.assertEqual(p.weapon_element, "dragon")
        self.assertEqual(p.weapon_id, 7)

    def test_save_load_roundtrip(self):
        p = Player(name="Sample Player", hr=3, potions=7)
        p.add(20, 5)
        p.equip(Equipment(1, "Blade", "blades", attack=90))
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "save.json")
            p.save(path)
            q = Player.load(path)
        self.assertEqual(q.name, "Sample Player")
        self.assertEqual(q.hr, 3)
        self.assertEqual(q.inventory, {20: 5})     # int keys survive the JSON round-trip
        self.assertEqual(q.weapon_attack, 90)

    def test_from_dict_ignores_unknown_keys(self):
        p = Player.from_dict({"name": "X", "bogus": 1, "inventory": {"5": 2}})
        self.assertEqual(p.name, "X")
        self.assertEqual(p.inventory, {5: 2})


if __name__ == "__main__":
    unittest.main()
