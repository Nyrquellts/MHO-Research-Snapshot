import unittest

from mho.status import Ailment, StatusTracker


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.tracker = StatusTracker({
            "poison": Ailment("poison", 60, 30, 105, 4, 2, 0),
            "paralysis": Ailment("paralysis", 75, 10, 110, 0, 0, 3),
            "sleep": Ailment("sleep", 90, 0, 90, 0, 0, 2),
        })

    def test_poison_builds_up_and_increases_tolerance(self):
        self.assertIsNone(self.tracker.apply("poison", 48))
        effect = self.tracker.apply("poison", 12)
        self.assertEqual((effect.kind, effect.dmg_per_tick, effect.ticks), ("dot", 4, 2))
        self.assertEqual(self.tracker.threshold("poison"), 90)
        self.assertIsNone(self.tracker.apply("poison", 60))
        self.assertIsNotNone(self.tracker.apply("poison", 30))
        self.assertEqual(self.tracker.threshold("poison"), 105)

    def test_paralysis_immobilizes(self):
        effect = self.tracker.apply("paralysis", 75)
        self.assertEqual((effect.kind, effect.duration), ("immobilize", 3))

    def test_sleep_has_its_own_effect(self):
        effect = self.tracker.apply("sleep", 90)
        self.assertEqual((effect.kind, effect.duration), ("sleep", 2))

    def test_unknown_or_nonpositive_application_is_ignored(self):
        self.assertIsNone(self.tracker.apply("blast", 999))
        self.assertIsNone(self.tracker.apply("poison", -80))
        self.assertIsNotNone(self.tracker.apply("poison", 60))


if __name__ == "__main__":
    unittest.main()
