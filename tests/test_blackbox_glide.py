import math
import unittest

from mho.blackbox import glide


def bb(**values):
    """A blackboard: ``{name: {"value": "3"}}``."""
    return {k: {"value": str(v)} for k, v in values.items()}


def clip(path_m: float, dur: float) -> dict:
    """A clip whose root walks ``path_m`` metres forward in ``dur`` seconds (a ``pos`` curve of [time, x, y] samples)."""
    return {"dur": dur, "pos": [[0.0, 0.0, 0.0], [dur / 2, 0.0, path_m / 2], [dur, 0.0, path_m]]}


def sets_speed(anim: str, *values) -> dict:
    """A sequence that plays ``anim`` and sets MoveSpeed from up to three values (numbers or ``state.<name>``)."""
    v = list(values) + ["0"] * (3 - len(values))
    return {"t": "Sequence", "c": [
        {"t": "Action", "a": {"Operation": "PlayClip", "Clip": anim}},
        {"t": "Action", "a": {"Operation": "SetState", "KeyName": "MoveSpeed", "Value1": str(v[0]), "Value2": str(v[1]), "Value3": str(v[2])}}]}


def profile(blackboard=None, clips=None, trees=None) -> dict:
    return {"blackboard": blackboard or {}, "clips": clips or {}, "trees": trees or {}}


def walking(mid, anim, t0, n, mps, heading=0.0, yaw=0.0, x0=0.0, y0=0.0, dt=0.1, d=10.0):
    """``n`` steps of ``dt`` seconds of monster ``mid`` in animation ``anim``, moving ``mps`` m/s towards ``heading`` (yaw convention: 0 is +y) while it faces ``yaw``."""
    a = math.radians(heading + 90.0)
    rows = []
    for i in range(n + 1):
        s = mps * dt * i
        rows.append({"t": round(t0 + dt * i, 3), "e": "mon", "id": mid, "x": x0 + s * math.cos(a), "y": y0 + s * math.sin(a), "yaw": yaw, "anim": anim, "d": d})
    return rows


def meter(rows, table, mid=33):
    return glide.measure(glide.monster_series(rows)[mid], table)


STRIDE = profile(
    clips={"Move_Run": clip(4.0, 1.0)},
    trees={"main": sets_speed("Move_Walk", "0", "state.WalkSpeed", "0")},
    blackboard=bb(WalkSpeed=2.0),
)
GAITED = profile(blackboard=bb(MoveSpeed_Walk=3.0, MoveSpeed_Run=3.0, MaxRunSpeed=10.0, MoveSpeed_Submerge=12.0))


class MotionTableTest(unittest.TestCase):
    def test_a_clip_that_moves_the_root_has_the_speed_of_its_path(self):
        t = glide.motion_table(STRIDE)
        self.assertEqual((t["anims"]["move_run"]["root"], t["anims"]["move_run"]["dur"]), (4.0, 1.0))

    def test_a_clip_of_no_length_moves_nothing(self):
        t = glide.motion_table(profile(clips={"Blink": clip(5.0, 0.04), "Flat": {"dur": 2.0, "pos": []}, "Odd": {"dur": 1.0, "pos": [[0, 0, 0], "x", None]}}))
        self.assertEqual([t["anims"][k]["root"] for k in ("blink", "flat", "odd")], [0.0, 0.0, 0.0])

    def test_a_set_speed_belongs_to_the_animation_its_sequence_plays_and_is_the_length_of_the_vector(self):
        t = glide.motion_table(profile(trees={"a": sets_speed("Move_Dash", "3", "0", "4")}))
        self.assertEqual(t["anims"]["move_dash"]["set"], [5.0])
        self.assertEqual(t["anims"]["move_dash"]["unresolved"], [])

    def test_a_blackboard_name_is_read_from_the_blackboard_and_the_animation_name_is_not_case_sensitive(self):
        t = glide.motion_table(STRIDE)
        self.assertEqual(t["anims"]["move_walk"]["set"], [2.0])

    def test_a_name_the_blackboard_gives_no_value_is_unresolved_and_sets_no_speed(self):
        t = glide.motion_table(profile(trees={"a": sets_speed("Move_Run", "0", "state.MoveSpeed_Run", "0")}, blackboard=bb(MoveSpeed_Walk=3.0)))
        self.assertEqual(t["anims"]["move_run"]["set"], [])
        self.assertEqual(t["anims"]["move_run"]["unresolved"], ["MoveSpeed_Run"])
        self.assertEqual(t["unresolved"], ["MoveSpeed_Run"])

    def test_a_blackboard_with_a_speed_per_gait_is_gait_driven_and_one_with_only_maxima_is_not(self):
        self.assertTrue(glide.motion_table(GAITED)["gait_driven"])
        t = glide.motion_table(profile(blackboard=bb(MaxRunSpeed=11.4, MaxWalkSpeed=3.0, MaxTurnRotateSpeed=90)))
        self.assertFalse(t["gait_driven"])
        self.assertEqual(t["gaits"], {"MaxRunSpeed": 11.4, "MaxWalkSpeed": 3.0})           # (a turn rate is not a speed)

    def test_what_is_not_a_profile_is_an_empty_table(self):
        for odd in (None, [], "x", {"blackboard": 3, "clips": [], "trees": 7}):
            t = glide.motion_table(odd)
            self.assertEqual((t["anims"], t["gaits"], t["gait_driven"]), ({}, {}, False))


class MeterTest(unittest.TestCase):
    def test_movement_in_an_animation_with_a_set_speed_is_in_the_data(self):
        r = meter(walking(33, "Move_Walk", 0, 50, 2.0), glide.motion_table(STRIDE))
        self.assertEqual((r["moved_m"], r["by_kind"], r["unaccounted_m"], r["nodata_m"]), (10.0, {"set": 10.0}, 0.0, 0.0))
        self.assertFalse(glide.is_glide(r))

    def test_movement_in_a_clip_that_moves_the_root_is_in_the_data_and_may_go_any_way(self):
        r = meter(walking(33, "Move_Run", 0, 30, 4.0, heading=-90.0), glide.motion_table(STRIDE))      # facing +y, going +x
        self.assertEqual((r["by_kind"], r["sideways_m"], r["unaccounted_m"]), ({"root": 12.0}, 0.0, 0.0))

    def test_movement_where_the_data_gives_no_motion_and_names_no_speed_is_a_glide(self):
        r = meter(walking(33, "Move_Slide", 0, 40, 3.0), glide.motion_table(STRIDE))
        self.assertEqual((r["moved_m"], r["unaccounted_m"], r["by_kind"]), (12.0, 12.0, {"none": 12.0}))
        self.assertTrue(glide.is_glide(r))
        slot = r["anims"]["Move_Slide"]
        self.assertEqual((slot["kind"], slot["mean_mps"], slot["m"], slot["s"]), ("none", 3.0, 12.0, 4.0))

    def test_a_glide_must_be_a_real_length_and_a_real_share_of_what_the_monster_moved(self):
        t = glide.motion_table(STRIDE)
        short = meter(walking(33, "Move_Walk", 0, 400, 2.0) + walking(33, "Move_Slide", 40.1, 10, 3.0, y0=80.0), t)         # 80 m in its data, 3 m outside it
        self.assertEqual((short["unaccounted_m"], short["moved_m"]), (3.0, 83.0))
        self.assertFalse(glide.is_glide(short))                                                                              # under 5 m: not worth a line
        small = meter(walking(33, "Move_Walk", 0, 4000, 2.0) + walking(33, "Move_Slide", 400.1, 20, 3.0, y0=800.0), t)      # 800 m in its data, 6 m outside it
        self.assertEqual((small["unaccounted_m"], small["moved_m"]), (6.0, 806.0))
        self.assertFalse(glide.is_glide(small))                                                                              # under 10 % of what it moved
        real = meter(walking(33, "Move_Walk", 0, 400, 2.0) + walking(33, "Move_Slide", 40.1, 60, 3.0, y0=80.0), t)         # 18 m outside of 98
        self.assertEqual((real["unaccounted_m"], real["moved_m"]), (18.0, 98.0))
        self.assertTrue(glide.is_glide(real))

    def test_the_share_edge(self):
        self.assertTrue(glide.is_glide({"unaccounted_m": 10.0, "moved_m": 100.0}))
        self.assertFalse(glide.is_glide({"unaccounted_m": 9.9, "moved_m": 100.0}))
        self.assertFalse(glide.is_glide({"unaccounted_m": 10.0, "moved_m": 101.0}))
        self.assertFalse(glide.is_glide({"unaccounted_m": None, "moved_m": 100.0}))

    def test_a_gait_driven_monster_is_never_a_glide_it_is_no_data(self):
        t = glide.motion_table(GAITED)
        r = meter(walking(33, "Move_Walk", 0, 40, 8.0), t)
        self.assertEqual((r["unaccounted_m"], r["nodata_m"], r["by_kind"]), (0.0, 32.0, {"nodata": 32.0}))
        self.assertTrue(glide.has_no_data(r))
        self.assertFalse(glide.is_glide(r))

    def test_a_speed_the_data_names_without_giving_is_no_data_too(self):
        t = glide.motion_table(profile(trees={"a": sets_speed("Move_Run", "0", "state.MoveSpeed_Run", "0")}))
        r = meter(walking(33, "Move_Run", 0, 40, 5.0), t)
        self.assertEqual((r["unaccounted_m"], r["nodata_m"]), (0.0, 20.0))

    def test_a_measured_speed_is_named_after_the_entitys_own_speeds_it_equals(self):
        t = glide.motion_table(GAITED)
        slow = meter(walking(33, "Move_Walk", 0, 40, 3.0), t)["anims"]["Move_Walk"]
        fast = meter(walking(33, "Move_Walk", 0, 40, 8.0), t)["anims"]["Move_Walk"]
        self.assertEqual(slow["matches"], ["MoveSpeed_Run", "MoveSpeed_Walk"])
        self.assertEqual(fast["matches"], [])
        self.assertEqual(glide.gait_matches(t, 3.1), ["MoveSpeed_Run", "MoveSpeed_Walk"])      # within 5 %
        self.assertEqual(glide.gait_matches(t, 3.2), [])
        self.assertEqual(glide.gait_matches(None, 3.0), [])

    def test_a_monster_without_a_profile_has_no_glide_to_find_and_its_metres_are_no_data(self):
        r = meter(walking(33, "Move_Walk", 0, 40, 3.0), None)
        self.assertEqual((r["unaccounted_m"], r["nodata_m"], r["by_kind"]), (None, 12.0, {"noprofile": 12.0}))
        self.assertFalse(glide.is_glide(r))

    def test_movement_in_no_named_animation_is_outside_the_data(self):
        r = meter(walking(33, "", 0, 40, 3.0), glide.motion_table(STRIDE))
        self.assertEqual((r["by_kind"], r["unaccounted_m"]), ({"unnamed": 12.0}, 12.0))

    def test_sideways_is_a_step_more_than_45_degrees_off_the_facing_without_root_motion(self):
        t = glide.motion_table(STRIDE)
        straight = meter(walking(33, "Move_Walk", 0, 40, 2.0), t)
        crab = meter(walking(33, "Move_Walk", 0, 40, 2.0, heading=-90.0), t)
        slight = meter(walking(33, "Move_Walk", 0, 40, 2.0, heading=-40.0), t)
        back = meter(walking(33, "Move_Walk", 0, 40, 2.0, heading=180.0), t)
        self.assertEqual([r["sideways_m"] for r in (straight, crab, slight, back)], [0.0, 8.0, 0.0, 8.0])
        self.assertTrue(glide.is_sideways(crab))
        self.assertFalse(glide.is_sideways(straight))
        self.assertEqual(crab["anims"]["Move_Walk"]["side_m"], 8.0)

    def test_the_angle_is_taken_against_the_yaw_whichever_way_it_is_turned(self):
        t = glide.motion_table(STRIDE)
        r = meter(walking(33, "Move_Walk", 0, 40, 2.0, heading=-90.0, yaw=-90.0), t)         # going +x while facing +x
        self.assertEqual(r["sideways_m"], 0.0)
        r = meter(walking(33, "Move_Walk", 0, 40, 2.0, heading=170.0, yaw=-175.0), t)       # across the +-180 seam: 15 degrees apart
        self.assertEqual(r["sideways_m"], 0.0)

    def test_a_row_without_a_yaw_is_no_verdict_on_the_direction(self):
        rows = walking(33, "Move_Walk", 0, 40, 2.0, heading=-90.0)
        for row in rows:
            del row["yaw"]
        self.assertEqual(meter(rows, glide.motion_table(STRIDE))["sideways_m"], 0.0)

    def test_the_step_an_animation_changes_in_belongs_to_neither(self):
        rows = walking(33, "Move_Walk", 0, 20, 2.0) + walking(33, "Move_Slide", 2.1, 20, 2.0, y0=4.2)
        r = meter(rows, glide.motion_table(STRIDE))
        self.assertEqual(r["transition_m"], 0.2)
        self.assertEqual(r["by_kind"], {"set": 4.0, "none": 4.0})

    def test_standing_and_gaps_are_not_steps(self):
        rows = walking(33, "Move_Walk", 0, 20, 0.2) + walking(33, "Move_Walk", 60.0, 5, 2.0) + [dict(r, t=r["t"] + 5.0) for r in walking(33, "Move_Walk", 60.0, 5, 2.0, y0=1000.0)]
        r = meter(rows, glide.motion_table(STRIDE))
        self.assertEqual(r["moved_m"], 2.0)                                    # the two half-second walks; neither the stand (0.2 m/s) nor the jump across a 4.5-second gap

    def test_a_damaged_row_is_a_step_that_is_skipped(self):
        rows = walking(33, "Move_Walk", 0, 20, 2.0)
        rows[5]["x"] = "far"
        rows[6]["t"] = None
        rows.append({"e": "mon", "id": 33})
        r = meter(rows, glide.motion_table(STRIDE))
        self.assertGreater(r["moved_m"], 3.0)

    def test_a_run_is_compared_with_the_clips_own_path(self):
        t = glide.motion_table(profile(clips={"Move_Dash": clip(6.0, 1.0)}))
        rows = []
        for i in range(4):                                                      # four runs of one second, 6 m each, apart
            rows += walking(33, "Move_Dash", 10.0 * i, 10, 6.0, y0=100.0 * i)
            rows += walking(33, "Idle", 10.0 * i + 1.1, 3, 0.0, y0=100.0 * i + 6.0)
        r = meter(rows, t)
        slot = r["anims"]["Move_Dash"]
        self.assertEqual((slot["kind"], slot["runs"], slot["run_m"], slot["clip_m"]), ("root", 4, 6.0, 6.0))
        self.assertEqual(glide.clip_lines(r), ["Move_Dash: 4 runs of 6 m on average, the clip's own path is 6 m"])

    def test_a_clip_line_wants_three_runs(self):
        t = glide.motion_table(profile(clips={"Move_Dash": clip(6.0, 1.0)}))
        rows = walking(33, "Move_Dash", 0, 10, 6.0) + walking(33, "Idle", 1.1, 3, 0.0, y0=6.0) + walking(33, "Move_Dash", 10, 10, 6.0, y0=100.0)
        self.assertEqual(glide.clip_lines(meter(rows, t)), [])


class AnalyseTest(unittest.TestCase):
    def test_every_monster_that_moved_far_enough_is_measured_against_its_own_entity(self):
        rows = walking(17, "Move_Slide", 0, 100, 3.0) + walking(33, "Move_Walk", 0, 100, 2.0) + walking(49, "Move_Walk", 0, 10, 2.0)    # 30 m, 20 m, 2 m
        tables = {"ExampleAlpha": glide.motion_table(STRIDE), "ExampleBeta": glide.motion_table(GAITED)}
        out = glide.analyse(rows, {17: "ExampleAlpha", 33: "ExampleBeta", 49: "ExampleBeta", 65: "Nowhere"}, tables)
        self.assertEqual(sorted(out), [17, 33])                                 # 49 moved 2 m: not worth a line
        self.assertEqual((out[17]["entity"], out[17]["profile"], out[17]["unaccounted_m"]), ("ExampleAlpha", True, 30.0))
        self.assertEqual((out[33]["nodata_m"], out[33]["unaccounted_m"], out[33]["gaits"]["MoveSpeed_Walk"]), (20.0, 0.0, 3.0))

    def test_a_monster_the_log_does_not_name_has_no_profile(self):
        out = glide.analyse(walking(17, "Move_Walk", 0, 100, 3.0), {}, {})
        self.assertEqual((out[17]["entity"], out[17]["profile"], out[17]["unaccounted_m"], out[17]["nodata_m"]), (None, False, None, 30.0))


class RateTest(unittest.TestCase):
    def test_a_drive_behind_the_frame_rate_and_over_the_bound_is_a_problem(self):
        r = glide.rate_check(50.0, 125.0, 20.0)
        self.assertEqual((r["behind"], r["per_frame"], r["level"]), (True, 0.4, "PROBLEM"))

    def test_over_the_bound_at_the_frame_rate_is_a_watch_and_under_it_is_nothing(self):
        self.assertEqual(glide.rate_check(50.0, 50.0, 20.0)["level"], "WATCH")           # one placement a frame: not behind, but a fast monster is 40 cm off
        self.assertIsNone(glide.rate_check(50.0, 50.0, 8.0)["level"])                   # 16 cm
        self.assertIsNone(glide.rate_check(330.0, 125.0, 30.0)["level"])
        self.assertIsNone(glide.rate_check(50.0, 125.0, 0)["level"])                      # no speed kept: no judgement
        self.assertIsNone(glide.rate_check(50.0, 125.0)["level"])

    def test_the_bound_edge(self):
        self.assertFalse(glide.rate_check(100.0, 100.0, 17.0)["over"])                    # exactly 17 cm
        self.assertTrue(glide.rate_check(100.0, 100.0, 17.1)["over"])

    def test_an_unknown_rate_is_no_verdict_and_an_unknown_frame_rate_is_not_behind(self):
        for hz in (None, 0, -1):
            self.assertIsNone(glide.rate_check(hz, 60.0, 20.0))
        for fps in (None, 0, -1):
            r = glide.rate_check(50.0, fps, 20.0)
            self.assertEqual((r["fps"], r["per_frame"], r["behind"], r["level"]), (None, None, False, "WATCH"))


class TeleportTest(unittest.TestCase):
    def rows(self):
        walk = walking(33, "Lame", 0, 20, 2.0)                                                         # 4 m north in 2 s
        far = walking(33, "Lame", 2.1, 20, 2.0, x0=walk[-1]["x"] + 500.0, y0=walk[-1]["y"])          # put 1,319.5 m east in 0.1 s, then 4 m more
        return walk + far

    def test_a_placement_is_in_no_meter(self):
        r = meter(self.rows(), glide.motion_table(STRIDE))
        self.assertEqual((r["moved_m"], r["by_kind"], r["unaccounted_m"], r["sideways_m"]), (8.0, {"none": 8.0}, 8.0, 0.0))
        self.assertEqual((r["teleport_n"], r["teleport_m"], r["teleports"]), (1, 500.0, [{"t": 2.0, "m": 500.0, "anim": "Lame"}]))
        slot = r["anims"]["Lame"]
        self.assertEqual((slot["all_m"], slot["runs"], slot["run_m"]), (8.0, 2, 4.0))                  # the teleport ends a run

    def test_a_step_under_the_bar_is_a_walk(self):
        r = meter(walking(33, "Move_Walk", 0, 10, 90.0), glide.motion_table(STRIDE))
        self.assertEqual((r["moved_m"], r["teleport_n"], r["teleports"]), (90.0, 0, []))

    def test_a_clips_peak_is_its_fastest_tenth_of_a_second_not_its_average(self):
        pos = [[0.0, 0.0, 0.0, 0.0], [0.05, 0.0, 1.0, 0.0], [0.1, 0.0, 2.0, 0.0], [1.0, 0.0, 3.0, 0.0]]
        self.assertAlmostEqual(20.0, glide.peak_speed(pos))                                             # 2 m in its first 0.1 s
        self.assertAlmostEqual(3.0, glide._path_speed(pos, 1.0))                                        # its average: 3 m in 1 s
        self.assertEqual(0.0, glide.peak_speed([[0.0, 0.0, 0.0, 0.0], [0.05, 0.0, 1.0, 0.0]]))          # shorter than the window
        self.assertEqual((0.0, 0.0), (glide.peak_speed(None), glide.peak_speed([["x"], 3])))

    def test_a_mark_across_a_placement_reads_the_speed_on_its_own_side_and_names_the_placement(self):
        series = glide.monster_series(self.rows())
        moving = glide.mark_motion(series, 33, 2.3)
        self.assertEqual((moving["anim"], moving["speed_mps"], moving["placed_m"]), ("Lame", 2.0, [500.0]))
        before = glide.mark_motion(series, 33, 1.9)                                                     # the nearest row is on the walk's side
        self.assertEqual((before["speed_mps"], before["placed_m"]), (2.0, [500.0]))
        self.assertNotIn("placed_m", glide.mark_motion(series, 33, 1.0))
