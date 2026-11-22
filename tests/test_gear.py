import unittest

from mho.gear import ArmorPiece, EquipSkill, SkillTier, assemble_loadout, resolve_skills


def catalog():
    return {
        "balance": EquipSkill(
            "balance", "Balance", [SkillTier(4, "Steady", ""), SkillTier(8, "Poised", "")]
        ),
        "power": EquipSkill("power", "Power", [SkillTier(5, "Strong", "")]),
    }


class GearTest(unittest.TestCase):
    def test_level_thresholds(self):
        skill = catalog()["balance"]
        self.assertEqual([skill.level_for(value) for value in (3, 4, 7, 8, 9)], [0, 1, 1, 2, 2])

    def test_resolve_skills(self):
        self.assertEqual(
            resolve_skills({"balance": 8, "power": 4, "unknown": 10}, catalog()),
            {"balance": (2, "Poised")},
        )

    def test_assemble_uses_secondary_skill_and_defense_as_tiebreaks(self):
        armor = {
            1: ArmorPiece(1, "Plain Cap", 1, 20, "", {"balance": 4}),
            2: ArmorPiece(2, "Lined Cap", 1, 15, "", {"balance": 4, "power": 2}),
            3: ArmorPiece(3, "Light Vest", 2, 15, "", {"balance": 3, "power": -1}),
            4: ArmorPiece(4, "Lined Vest", 2, 25, "", {"balance": 3, "power": -1}),
        }
        loadout = assemble_loadout(
            armor, catalog(), slots=(1, 2, 3), preferred_groups=("balance",), tiebreak_group="power",
        )
        self.assertEqual([piece.item_id for piece in loadout.pieces], [2, 4])
        self.assertEqual(loadout.points, {"balance": 7, "power": 1})
        self.assertEqual(loadout.skills, {"balance": (1, "Steady")})
        self.assertEqual(loadout.total_defense, 40)


if __name__ == "__main__":
    unittest.main()
