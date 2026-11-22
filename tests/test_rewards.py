import random
import unittest

from mho.rewards import DropEntry, DropTable


class DropTableTest(unittest.TestCase):
    def test_roll_fills_slots_and_is_deterministic(self):
        t = DropTable([DropEntry(100, 1, 1, 90), DropEntry(200, 2, 3, 10)])
        a = t.roll(random.Random(1), slots=3)
        b = t.roll(random.Random(1), slots=3)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 3)
        for item, qty in a:
            self.assertIn(item, (100, 200))
            self.assertGreaterEqual(qty, 1)

    def test_weight_bias(self):
        t = DropTable([DropEntry(100, 1, 1, 95), DropEntry(200, 1, 1, 5)])
        rng = random.Random(4)
        c = {100: 0, 200: 0}
        for _ in range(2000):
            for item, _q in t.roll(rng, 1):
                c[item] += 1
        self.assertGreater(c[100], c[200] * 5)

    def test_empty_pool(self):
        self.assertEqual(DropTable([]).roll(random.Random(), 3), [])


if __name__ == "__main__":
    unittest.main()
