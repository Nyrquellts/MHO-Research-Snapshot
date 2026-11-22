import unittest

from mho.quests import Quest, QuestPay, hunt_quests


class QuestTest(unittest.TestCase):
    def test_hunt_quests_filter(self):
        trial = Quest(1, "Sample trial", "", 17, 2, 1, 180, 1, 1, False)
        gathering = Quest(2, "Sample gathering", "", 0, 1, 3, 0, 2, 0, True)
        self.assertEqual(hunt_quests([trial, gathering], {17}), [trial])

    def test_pay_adds_each_balance(self):
        taken = QuestPay(0, 5, 10)
        handed_in = QuestPay(200, 0, 600)
        self.assertEqual((taken + handed_in).as_tuple(), (200, 5, 610))
        self.assertEqual(taken + QuestPay(), taken)


if __name__ == "__main__":
    unittest.main()
