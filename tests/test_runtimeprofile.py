"""Standalone tests for runtime profile grammar, precedence, and rates."""
import os
import tempfile
import unittest


from mho import runtimeprofile as rp

# (line, valid, name, the subsystems on, the unknown words)
VECTORS = [
    ("legacy165", True, "legacy165", (), ()),
    ("LEGACY165", True, "legacy165", (), ()),
    ("repair60", True, "repair60", rp.SUBSYSTEMS, ()),
    ("Repair60", True, "repair60", rp.SUBSYSTEMS, ()),
    ("repair60.clock", True, "repair60", ("clock",), ()),
    ("repair60.clock repair60.reactions", True, "repair60", ("clock", "reactions"), ()),
    ("repair60.reactions,repair60.clock", True, "repair60", ("clock", "reactions"), ()),
    ("repair60.clock;\trepair60.hp_ui", True, "repair60", ("clock", "hp_ui"), ()),
    ("repair60 -reactions -hitfly", True, "repair60", ("clock", "movement_sync", "hp_ui", "world_movement", "input_hold", "parts", "attacks", "aim", "damage", "region_walk", "gauge", "faction", "flight"), ()),
    ("repair60 -clock", True, "repair60", ("movement_sync", "reactions", "hitfly", "hp_ui", "world_movement", "input_hold", "parts", "attacks", "aim", "damage", "region_walk", "gauge", "faction", "flight"), ()),
    ("repair60 -clock -movement_sync -reactions -hitfly -hp_ui -world_movement -input_hold -parts -attacks -aim -damage -region_walk -gauge -faction -flight", True, "repair60", (), ()),
    ("repair60 -clock -movement_sync -reactions -hitfly -hp_ui -world_movement", True, "repair60", ("input_hold", "parts", "attacks", "aim", "damage", "region_walk", "gauge", "faction", "flight"), ()),
    ("repair60 -clock -movement_sync -reactions -hitfly -hp_ui -world_movement -input_hold", True, "repair60", ("parts", "attacks", "aim", "damage", "region_walk", "gauge", "faction", "flight"), ()),
    ("repair60.clock -clock", True, "repair60", (), ()),
    ("repair60 -movement_sync repair60.movement_sync", True, "repair60", rp.SUBSYSTEMS, ()),
    ("  repair60.clock  ", True, "repair60", ("clock",), ()),
    ("legacy165 repair60", False, "legacy165", (), ("repair60",)),
    ("legacy165 -clock", False, "legacy165", (), ("-clock",)),
    ("repair60 bogus", False, "legacy165", (), ("bogus",)),
    ("repair60.bogus", False, "legacy165", (), ("repair60.bogus",)),
    ("repair60 -bogus", False, "legacy165", (), ("-bogus",)),
    ("repair60 -", False, "legacy165", (), ("-",)),
    ("repair60 clock", False, "legacy165", (), ("clock",)),
    ("repair60clock", False, "legacy165", (), ("repair60clock",)),
    ("repair", False, "legacy165", (), ("repair",)),
    ("60", False, "legacy165", (), ("60",)),
    ("legacy", False, "legacy165", (), ("legacy",)),
    (",", False, "legacy165", (), (",",)),
    (" ; , ", False, "legacy165", (), ("; ,",)),
]


class GrammarTest(unittest.TestCase):
    def test_every_vector_matches_the_expected_profile(self):
        for line, ok, name, on, unknown in VECTORS:
            with self.subTest(line=line):
                p = rp.parse(line)
                self.assertEqual(name, p.name)
                self.assertEqual(frozenset(on), p.on)
                self.assertEqual(tuple(unknown), p.unknown)
                self.assertEqual(ok, rp.valid(line))
                self.assertEqual(ok, not p.unknown)


    def test_blank_and_none_are_the_baseline_and_not_a_valid_line(self):
        for text in (None, "", "   ", "\t"):
            with self.subTest(text=repr(text)):
                self.assertIs(rp.LEGACY_PROFILE, rp.parse(text))
                self.assertFalse(rp.valid(text))

    def test_the_shortest_line_for_a_profile_is_the_servers(self):
        self.assertEqual("legacy165", str(rp.parse("legacy165")))
        self.assertEqual("legacy165", str(rp.parse("repair60 bogus")))                   # invalid plays the baseline
        self.assertEqual("repair60", str(rp.parse("repair60")))
        self.assertEqual("repair60", str(rp.parse("repair60.clock repair60.movement_sync repair60.reactions repair60.hitfly repair60.hp_ui repair60.world_movement "
                                                  "repair60.input_hold repair60.parts repair60.attacks repair60.aim repair60.damage repair60.region_walk repair60.gauge repair60.faction repair60.flight")))
        self.assertEqual("repair60.clock repair60.reactions", str(rp.parse("repair60.reactions repair60.clock")))
        self.assertEqual("repair60 -clock -movement_sync -reactions -hitfly -hp_ui -world_movement -input_hold -parts -attacks -aim -damage -region_walk -gauge -faction -flight", str(rp.parse("repair60.clock -clock")))
        for line, ok, *_ in VECTORS:
            if ok:
                with self.subTest(line=line):
                    self.assertEqual(rp.parse(line), rp.parse(str(rp.parse(line))))     # the shortest line parses back to the same profile

    def test_the_seams(self):
        self.assertTrue(rp.parse("repair60").clock)
        self.assertTrue(rp.parse("repair60.clock").clock)
        self.assertFalse(rp.parse("repair60 -clock").clock)
        self.assertFalse(rp.parse("repair60.reactions").clock)
        self.assertFalse(rp.LEGACY_PROFILE.clock)
        self.assertTrue(rp.REPAIR_PROFILE.is_repair60 and rp.REPAIR_PROFILE.has("hp_ui"))
        self.assertFalse(rp.LEGACY_PROFILE.has("clock") or rp.LEGACY_PROFILE.has(None))


class LoaderTest(unittest.TestCase):
    def test_the_variable_wins_then_the_file_then_the_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIs(rp.LEGACY_PROFILE, rp.load({}, d))                               # no file
            with open(os.path.join(d, rp.FILE_NAME), "w", encoding="utf-8") as f:
                f.write("# a comment\n\n   # another\nrepair60.clock\nrepair60\n")
            self.assertEqual(frozenset({"clock"}), rp.load({}, d).on)                        # the first profile line, not the second
            self.assertEqual(frozenset({"clock"}), rp.load({rp.VARIABLE: "  "}, d).on)      # a blank variable does not name anything
            self.assertEqual(rp.REPAIR_PROFILE, rp.load({rp.VARIABLE: "repair60"}, d))      # the variable wins over the file
            self.assertEqual(("bogus",), rp.load({rp.VARIABLE: "bogus"}, d).unknown)         # an invalid variable is not rescued by the file
            self.assertIs(rp.LEGACY_PROFILE, rp.load({}, None))                            # no folder given: the environment alone
            with open(os.path.join(d, rp.FILE_NAME), "w", encoding="utf-8") as f:
                f.write("# only comments\n")
            self.assertIs(rp.LEGACY_PROFILE, rp.load({}, d))
        self.assertEqual(rp.REPAIR_PROFILE, rp.current({rp.VARIABLE: "REPAIR60"}))
        self.assertIs(rp.LEGACY_PROFILE, rp.current({}))

    def test_first_line_reads_nothing_it_cannot(self):
        self.assertIsNone(rp.first_line(os.path.join(tempfile.gettempdir(), "no-such-folder-%d" % os.getpid(), rp.FILE_NAME)))


class DriveRateTest(unittest.TestCase):
    CASES = [
        ({}, 165.0),
        ({"MHO_DRIVE_HZ": "120"}, 120.0),
        ({"MHO_DRIVE_HZ": "62.5"}, 62.5),
        ({"MHO_DRIVE_HZ": "29"}, 165.0),
        ({"MHO_DRIVE_HZ": "fast"}, 165.0),
        ({"MHO_RUNTIME_PROFILE": "repair60"}, 60.0),
        ({"MHO_RUNTIME_PROFILE": "REPAIR60.CLOCK"}, 60.0),
        ({"MHO_RUNTIME_PROFILE": "repair60", "MHO_DRIVE_HZ": "120"}, 60.0),                 # the fixed step cannot be moved by the knob
        ({"MHO_RUNTIME_PROFILE": "repair60 -clock", "MHO_DRIVE_HZ": "120"}, 120.0),         # without the clock the baseline's drive, and its knob
        ({"MHO_RUNTIME_PROFILE": "repair60.reactions"}, 165.0),
        ({"MHO_RUNTIME_PROFILE": "legacy165"}, 165.0),
        ({"MHO_RUNTIME_PROFILE": "bogus"}, 165.0),                                           # an invalid line plays the baseline
        ({"MHO_RUNTIME_PROFILE": "bogus", "MHO_DRIVE_HZ": "120"}, 120.0),
    ]

    def test_the_rate_follows_the_profile_then_the_knob_then_the_default(self):
        for env, want in self.CASES:
            with self.subTest(env=env):
                self.assertEqual(want, rp.drive_hz(env))
                self.assertEqual(want if want != 165.0 else 100.0, rp.drive_hz(env, default=100.0))

    def test_the_servers_file_counts_when_the_probe_is_told_its_folder(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, rp.FILE_NAME), "w", encoding="utf-8") as f:
                f.write("repair60.clock\n")
            self.assertEqual(60.0, rp.drive_hz({}, files_dir=d))
            self.assertEqual(165.0, rp.drive_hz({rp.VARIABLE: "legacy165"}, files_dir=d))   # the variable wins over the file
            self.assertEqual(165.0, rp.drive_hz({}))                                        # not told the folder: the environment alone


class SyncRateTest(unittest.TestCase):
    """The rate a moving monster is placed on the wire at under each profile: the replication clock under repair60.movement_sync, else the drive's step (REPAIR60_MANIFEST.md,
    commit 5)."""

    # (environment, the replication clock, the placement rate)
    CASES = [
        ({}, 30.0, 165.0),
        ({"MHO_MONSTER_SYNC_HZ": "60"}, 60.0, 165.0),                                                  # the knob is read; the baseline does not place at it
        ({"MHO_RUNTIME_PROFILE": "repair60"}, 30.0, 30.0),
        ({"MHO_RUNTIME_PROFILE": "repair60", "MHO_MONSTER_SYNC_HZ": "60"}, 60.0, 60.0),
        ({"MHO_RUNTIME_PROFILE": "repair60", "MHO_MONSTER_SYNC_HZ": "9"}, 30.0, 30.0),                # out of range: the fallback
        ({"MHO_RUNTIME_PROFILE": "repair60", "MHO_MONSTER_SYNC_HZ": "121"}, 30.0, 30.0),
        ({"MHO_RUNTIME_PROFILE": "repair60", "MHO_MONSTER_SYNC_HZ": "fast"}, 30.0, 30.0),
        ({"MHO_RUNTIME_PROFILE": "repair60", "MHO_MONSTER_SYNC_HZ": "nan"}, 30.0, 30.0),
        ({"MHO_RUNTIME_PROFILE": "repair60.movement_sync"}, 30.0, 30.0),
        ({"MHO_RUNTIME_PROFILE": "repair60.movement_sync", "MHO_DRIVE_HZ": "120"}, 30.0, 30.0),       # the drive's knob does not move the replication clock
        ({"MHO_RUNTIME_PROFILE": "repair60 -movement_sync"}, 30.0, 60.0),                             # without the switch: the drive's step (the repair's clock)
        ({"MHO_RUNTIME_PROFILE": "repair60 -movement_sync -clock"}, 30.0, 165.0),
        ({"MHO_RUNTIME_PROFILE": "repair60 -movement_sync -clock", "MHO_DRIVE_HZ": "120"}, 30.0, 120.0),
        ({"MHO_RUNTIME_PROFILE": "legacy165", "MHO_MONSTER_SYNC_HZ": "60"}, 60.0, 165.0),
        ({"MHO_RUNTIME_PROFILE": "bogus"}, 30.0, 165.0),                                              # an invalid line plays the baseline
    ]

    def test_the_clock_and_the_placement_rate_follow_the_profile_and_the_knob(self):
        for env, sync, placed in self.CASES:
            with self.subTest(env=env):
                self.assertEqual(sync, rp.sync_hz(env))
                self.assertEqual(placed, rp.placement_hz(env))

    def test_the_profile_names_the_switch(self):
        self.assertTrue(rp.parse("repair60").movement_sync)
        self.assertTrue(rp.parse("repair60.movement_sync").movement_sync)
        self.assertFalse(rp.parse("repair60 -movement_sync").movement_sync)
        self.assertFalse(rp.parse("repair60.clock").movement_sync)
        self.assertFalse(rp.parse("legacy165").movement_sync)
        self.assertFalse(rp.parse(None).movement_sync)

    def test_the_servers_file_counts_when_told_the_folder(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, rp.FILE_NAME), "w", encoding="utf-8") as f:
                f.write("repair60\n")
            self.assertEqual(30.0, rp.placement_hz({}, files_dir=d))
            self.assertEqual(60.0, rp.placement_hz({rp.SYNC_VARIABLE: "60"}, files_dir=d))
            self.assertEqual(165.0, rp.placement_hz({rp.VARIABLE: "legacy165"}, files_dir=d))     # the variable wins over the file
            self.assertEqual(165.0, rp.placement_hz({}))                                            # not told the folder: the environment alone


if __name__ == "__main__":
    unittest.main()
