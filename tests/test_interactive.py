import unittest

from mho.combat import Hitzone, Monster, MonsterPart
from mho.interactive import InteractiveHunt
from mho.player import Player
from mho.rewards import DropEntry, DropTable


class SyntheticContent:
    def monster(self, monster_id):
        return self.monsters.get(monster_id)

    def name(self, monster_id):
        return self.monster_names[monster_id]

    def status_tracker(self, monster_id):
        return None

    def carves_for(self, monster_id):
        return {part: pool for (owner, part), pool in self.partbreak_carves.items() if owner == monster_id}

    def name_drops(self, drops):
        return ", ".join(f"{quantity} {self.item_names[item_id]}" for item_id, quantity in drops)


def _content(hp=200):
    c = SyntheticContent()
    c.monsters = {1: Monster(1, hp, 1.0, [MonsterPart("Head", Hitzone(cut=100), break_threshold=50),
                                          MonsterPart("Body", Hitzone(cut=40))])}
    c.monster_names = {1: "Dummy"}
    c.boss_drops = {1: DropTable([DropEntry(500, 1, 1, 100)])}
    c.capture_drops = {1: DropTable([DropEntry(600, 1, 1, 100)])}
    c.partbreak_carves = {(1, "Head"): DropTable([DropEntry(700, 1, 1, 100)])}
    c.capture_hp_percent = {1: 20.0}
    c.item_names = {500: "Scale", 600: "Gem", 700: "Horn"}
    return c


def _scripted(actions):
    """A get_action provider that returns queued actions, then flees."""
    it = iter(actions)
    return lambda hunt: next(it, ("flee",))


class InteractiveHuntTest(unittest.TestCase):
    def test_attacks_to_victory_with_drops(self):
        p = Player(weapon_attack=100)     # 48*100*1.0/def... strong
        hunt = InteractiveHunt(_content(hp=200), p, 1, defense=10, player_count=4, seed=1)
        out = []
        outcome = hunt.play(_scripted([("attack", "Head")] * 20), out.append)
        self.assertEqual(outcome, "victory")
        self.assertTrue(hunt.drops)
        self.assertTrue(any("PART BREAK" in ln for ln in out))     # Head breaks (threshold 50)

    def test_capture(self):
        p = Player(weapon_attack=100, max_hp=500)
        hunt = InteractiveHunt(_content(hp=200), p, 1, defense=10, player_count=4,
                               monster_touch_damage=1, seed=2)
        # attack until capturable, then capture
        acts = [("attack", "Body")] * 30
        outcome = hunt.play(lambda h: ("capture",) if h.capturable else acts.pop(0), lambda s: None)
        self.assertEqual(outcome, "capture")
        self.assertIn((600, 1), hunt.drops)      # capture pool

    def test_defeat(self):
        p = Player(weapon_attack=1, max_hp=30)
        hunt = InteractiveHunt(_content(hp=5000), p, 1, defense=50, player_count=4,
                               monster_touch_damage=20, seed=3)
        outcome = hunt.play(_scripted([("attack", "Head")] * 50), lambda s: None)
        self.assertEqual(outcome, "defeat")
        self.assertEqual(hunt.drops, [])

    def test_potion_heals(self):
        p = Player(weapon_attack=1, max_hp=100, potions=2)
        hunt = InteractiveHunt(_content(hp=5000), p, 1, defense=50, player_count=4,
                               monster_touch_damage=10, seed=1)
        hunt.player_hp = 40
        hunt.step(("potion",))
        self.assertEqual(hunt.potions, 1)
        self.assertGreater(hunt.player_hp, 40)   # healed (minus the monster's counter-hit)

    def test_unusable_part_falls_back_to_weakest_part(self):
        hunt = InteractiveHunt(_content(), Player(), 1, seed=1)
        lines = hunt.step(("attack", ["Head"]))
        self.assertTrue(any("you hit Head" in line for line in lines))

    def test_flee(self):
        hunt = InteractiveHunt(_content(), Player(), 1, seed=1)
        hunt.step(("flee",))
        self.assertEqual(hunt.outcome, "fled")


if __name__ == "__main__":
    unittest.main()
