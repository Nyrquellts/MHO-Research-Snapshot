import json
import math
import os
import tempfile
import unittest

from mho.blackbox import track


def evades(rows):
    return track.evades(rows, dodge_skills=frozenset({7}), perfect_skill=8, dodge_state="dodge")


def fifo(t, x, y, skill=0, s=(0, 0, 0, 0), sta=100, kind=1):
    return {"t": t, "e": "fifo", "p": [x, y, 20.0], "s": list(s), "ag": 0, "skill": skill, "lvl": 1, "sta": sta, "type": kind}


def ev(t, kind, **fields):
    return dict({"t": t, "e": kind}, **fields)


def run_rows(seconds=10.0, speed=6.0, rate=4.0):
    """The hunter runs along +y at ``speed``; their client reports every 1/rate seconds; the server's ``trk`` follows (10 a second)."""
    rows = [ev(0.0, "hunt", title="test")]
    n = int(seconds * rate)
    for i in range(n + 1):
        t = i / rate
        rows.append(fifo(t, 100.0, 100.0 + speed * t))
    return rows


class LoadTest(unittest.TestCase):
    def test_bad_lines_are_counted_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "track-x.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(ev(0.0, "hunt")) + "\n\n" + "{\"t\": 1.0, \"e\": \"fifo\"\n" + "[1, 2]\n" + json.dumps({"t": 2.0}) + "\n"
                        + json.dumps(ev(3.0, "end", lines=2, dropped=0)) + "\n")
            rows, bad = track.load(path)
        self.assertEqual([r["e"] for r in rows], ["hunt", "end"])
        self.assertEqual(bad, 3)


class SummaryTest(unittest.TestCase):
    def test_the_report_rate_the_gaps_and_the_hunters_speed(self):
        rows = run_rows(10.0, 6.0, 4.0) + [ev(2.0, "skill", id=7, lvl=4, type=2, name="Start"), ev(2.6, "skill", id=7, lvl=4, type=2, name="End")]
        s = track.summary(sorted(rows, key=lambda r: r["t"]))
        self.assertAlmostEqual(s["position_reports_per_s"], 4.1, delta=0.2)
        self.assertAlmostEqual(s["report_gap_s"]["median"], 0.25, places=3)
        self.assertAlmostEqual(s["hunter_speed_mps"]["median"], 6.0, places=1)
        self.assertEqual(s["skill_events"]["7:Start"], 1)
        self.assertEqual(s["events"]["fifo"], 41)

    def test_a_jump_is_not_a_speed(self):
        rows = [fifo(0.0, 0, 0), fifo(0.3, 900, 900), fifo(0.6, 900, 901.5)]
        self.assertLess(track.summary(rows)["hunter_speed_mps"]["max"], 10.0)

    def test_an_empty_recording_summarises_to_nothing(self):
        s = track.summary([])
        self.assertEqual((s["duration_s"], s["position_reports_per_s"]), (0.0, 0.0))


class EvadeTest(unittest.TestCase):
    def rows(self):
        return sorted([
            fifo(9.5, 100, 100), fifo(10.0, 100, 101, skill=7, s=(5, 0, 0, 0)), fifo(10.4, 100, 104, skill=7, s=(5, 0, 0, 0)),
            ev(10.0, "skill", id=7, lvl=4, type=2, name="Start"),
            ev(10.1, "mon", id=17, d=6.0), ev(10.3, "mon", id=17, d=3.2), ev(10.5, "mon", id=17, d=4.0),
            ev(10.7, "evade_end", sync=1, net=42), fifo(10.8, 100, 106, s=(1, 0, 0, 0)),
            # a perfect one
            ev(20.0, "skill", id=7, lvl=4, type=2, name="Start"), ev(20.1, "skill", id=8, lvl=3, type=3, name="PerfectEvadeStart"),
            fifo(20.3, 110, 100, skill=8, s=(9, 9, 0, 0)), ev(20.9, "skill", id=8, lvl=3, type=3, name="PerfectEvadeEnd"),
            ev(21.0, "evade_end", sync=2, net=42),
            # one whose end never came
            ev(30.0, "skill", id=7, lvl=4, type=2, name="Start"), fifo(30.2, 120, 100, skill=7, s=(5, 0, 0, 0), sta=0),
        ], key=lambda r: r["t"])

    def test_every_dodge_with_its_start_end_and_kind(self):
        windows = evades(self.rows())
        self.assertEqual(len(windows), 3)
        roll, perfect, lost = windows
        self.assertEqual((roll["start"], roll["end"], roll["duration"], roll["perfect"]), (10.0, 10.7, 0.7, False))
        self.assertEqual(roll["closest_monster_m"], 3.2)
        self.assertAlmostEqual(roll["moved_m"], 5.0, delta=0.5)                      # from the report at 10.0 to the one at 10.8 (those within 0.3 s of it)
        self.assertEqual(roll["last_state"]["s"], [5, 0, 0, 0])
        self.assertTrue(perfect["perfect"])
        self.assertEqual(perfect["skills"], [7, 8])
        self.assertIn("8/3:PerfectEvadeStart", perfect["events"])
        self.assertEqual(perfect["end"], 21.0)
        self.assertIsNone(lost["end"])
        self.assertIsNone(lost["duration"])
        self.assertEqual(track.unfinished(windows), [lost])
        self.assertEqual(lost["last_state"]["sta"], 0)

    def test_a_perfect_dodge_is_also_the_state_sync_in_the_perfect_evade_skill(self):
        rows = sorted([
            ev(40.0, "skill", id=7, lvl=4, type=3, name="Start"), fifo(40.2, 100, 100, skill=7, s=(5, 0, 0, 0)),
            fifo(40.3, 100, 100, skill=8, s=(9, 9, 0, 0), sta=84), ev(40.42, "evade_end", sync=3, net=1),
            fifo(60.0, 100, 100, s=(1, 0, 0, 0)),
        ], key=lambda r: r["t"])
        (window,) = evades(rows)
        self.assertTrue(window["perfect"])
        self.assertEqual(window["skills"], [7])                              # only the events name skills; the state sync is not one
        self.assertAlmostEqual(window["quiet_after"], 60.0 - 40.42, places=2)        # 19.6 s of nothing, then a report
        self.assertFalse(window["silent_to_end"])
        self.assertEqual(track.frozen([window]), [window])

    def test_a_roll_whose_start_event_was_never_reported_opens_a_window_by_its_state_sync(self):
        rows = sorted([
            fifo(48.026, 100, 100, skill=7, s=(5, 0, 0, 0), kind="dodge"), fifo(48.038, 100, 100, skill=8, s=(9, 9, 0, 0), sta=84, kind="dodge"),
            ev(48.269, "evade_end", sync=4, net=1),
            fifo(60.0, 100, 100, s=(1, 0, 0, 0)),
        ], key=lambda r: r["t"])
        (window,) = evades(rows)
        self.assertTrue(window["perfect"])
        self.assertEqual((window["start"], window["end"]), (48.026, 48.269))
        self.assertGreater(window["quiet_after"], 5.0)

    def test_a_late_repeat_of_a_rolls_state_is_its_tail_and_a_later_roll_is_another_dodge(self):
        rows = sorted([
            fifo(10.0, 100, 100, skill=7, s=(5, 0, 0, 0), kind="dodge"), ev(10.2, "evade_end", sync=1, net=1),
            fifo(10.35, 100, 100, skill=7, s=(5, 0, 0, 0), kind="dodge"),  # 0.15 s after the end: the tail of that roll
            fifo(12.0, 100, 100, skill=7, s=(5, 0, 0, 0), kind="dodge"), ev(12.2, "evade_end", sync=2, net=1),
        ], key=lambda r: r["t"])
        windows = evades(rows)
        self.assertEqual([(w["start"], w["end"]) for w in windows], [(10.0, 10.2), (12.0, 12.2)])

    def test_a_dodge_the_client_carried_on_after_is_not_frozen(self):
        rows = sorted([
            ev(10.0, "skill", id=7, lvl=4, type=3, name="Start"), ev(10.2, "evade_end", sync=1, net=1), fifo(10.5, 100, 100, s=(1, 0, 0, 0)),
            fifo(11.0, 100, 100, s=(1, 0, 0, 0)),
        ], key=lambda r: r["t"])
        (window,) = evades(rows)
        self.assertFalse(window["perfect"])
        self.assertAlmostEqual(window["quiet_after"], 0.3, places=2)
        self.assertEqual(track.frozen([window]), [])

    def test_a_dodge_with_nothing_after_it_says_the_silence_ran_to_the_end(self):
        rows = sorted([
            ev(10.0, "skill", id=7, lvl=4, type=3, name="Start"), ev(10.2, "evade_end", sync=1, net=1), ev(18.0, "mon", id=17, d=5.0),
        ], key=lambda r: r["t"])
        (window,) = evades(rows)
        self.assertTrue(window["silent_to_end"])
        self.assertAlmostEqual(window["quiet_after"], 7.8, places=2)                 # to the last row of the recording
        self.assertEqual(track.frozen([window]), [window])

    def test_no_dodge_no_windows(self):
        self.assertEqual(evades(run_rows(2.0)), [])

    def test_around_is_a_timeline_of_a_window_and_can_be_filtered(self):
        lines = track.around(self.rows(), 20.1, 0.3)
        self.assertEqual(len(lines), 3)
        self.assertIn("PerfectEvadeStart", "".join(lines))
        only = track.around(self.rows(), 20.1, 5.0, kinds=("evade_end",))
        self.assertEqual(len(only), 1)
        self.assertIn("evade_end", only[0])


class MonsterTest(unittest.TestCase):
    def test_a_heavy_turn_and_a_snap_are_told_apart(self):
        rows = []
        for i in range(20):
            rows.append(ev(i * 0.1, "mon", id=1, yaw=-170.0 + i * 9.0, x=0, y=0, z=0))     # 90 degrees a second
            rows.append(ev(i * 0.1, "mon", id=2, yaw=0.0 if i % 2 == 0 else 180.0, x=0, y=0, z=0))                                                # flips 180 every 0.1 s
        turns = track.monster_turns(rows)
        self.assertAlmostEqual(turns[1]["max_dps"], 90.0, delta=1.0)
        self.assertGreater(turns[2]["max_dps"], 1500.0)

    def test_the_turn_across_the_seam_is_short(self):
        rows = [ev(0.0, "mon", id=1, yaw=179.0), ev(0.1, "mon", id=1, yaw=-179.0)]
        self.assertAlmostEqual(track.monster_turns(rows)[1]["max_dps"], 20.0, delta=0.5)

    def test_the_ground_and_the_region(self):
        class Flat:
            def height(self, x, y):
                return 20.0 if x >= 0 else None

        rows = [ev(0.0, "mon", id=1, x=5.0, y=5.0, z=20.2), ev(0.1, "mon", id=1, x=6.0, y=5.0, z=20.4), ev(0.2, "mon", id=1, x=7.0, y=5.0, z=26.0),
                ev(0.3, "mon", id=2, x=-50.0, y=5.0, z=99.0)]
        errors = track.ground_error(rows, Flat())
        self.assertEqual(sorted(errors), [1])
        self.assertAlmostEqual(errors[1]["median_m"], 0.4, places=2)
        self.assertEqual(track.outside_regions(rows, lambda x, y: x >= 0), {2: 1})


class TurnCausesTest(unittest.TestCase):
    PROFILE = {"clips": {"TurnBack": {"dur": 0.5, "yaw": [[0.0, 0.0], [0.25, 90.0], [0.5, 180.0]]},   # 360 degrees a second
                         "Run": {"dur": 1.0}, "Idle": {"dur": 2.0, "yaw": [[0.0, 0.0], [2.0, 10.0]]}}}   # 5 degrees a second

    def rows(self, anims, step=90.0):
        return [ev(i * 0.1, "mon", id=1, yaw=-180.0 + i * step, anim=a) for i, a in enumerate(anims)]

    def test_clip_rates_are_the_fastest_instant_of_each_yaw_track(self):
        rates = track.clip_turn_rates(self.PROFILE)
        self.assertAlmostEqual(rates["turnback"], 360.0)
        self.assertEqual(rates["run"], 0.0)
        self.assertAlmostEqual(rates["idle"], 5.0)

    def test_clip_rates_of_something_that_is_not_a_profile_are_nothing(self):
        for junk in (None, [], "x", {}, {"clips": []}, {"clips": {"a": 5, "b": {"yaw": "no"}, "c": {"yaw": [[0, 0], [1, "x"], "junk"]}}}):
            self.assertIsInstance(track.clip_turn_rates(junk), dict)
        self.assertEqual({"a": 0.0, "b": 0.0, "c": 0.0}, track.clip_turn_rates({"clips": {"a": 5, "b": {"yaw": "no"}, "c": {"yaw": [[0, 0], [1, "x"]]}}}))

    def test_a_fast_turn_inside_a_turning_clip_is_explained(self):
        # 25 degrees in 0.1 s is 250 deg/s: over the 200 the steering allows, so it needs a cause -- the 360 deg/s clip (at least half the rate) is one
        c = track.turn_causes(self.rows(["TurnBack", "TurnBack"], step=25.0), track.clip_turn_rates(self.PROFILE))[1]
        self.assertEqual((c["samples"], c["fast"], c["explained"], c["unexplained_count"]), (1, 1, 1, 0))

    def test_a_fast_turn_that_no_clip_accounts_for_is_unexplained_and_listed(self):
        c = track.turn_causes(self.rows(["Run", "Run"], step=90.0), track.clip_turn_rates(self.PROFILE))[1]
        self.assertEqual((c["fast"], c["explained"], c["unexplained_count"]), (1, 0, 1))
        self.assertEqual(c["unexplained"], [{"t": 0.1, "dps": 900, "was": "Run", "anim": "Run", "clip_dps": 0}])

    def test_the_clip_of_the_sample_before_counts_too(self):
        # the turn clip ended between the two samples: the turn belongs to it
        c = track.turn_causes(self.rows(["TurnBack", "Run"], step=30.0), track.clip_turn_rates(self.PROFILE))[1]
        self.assertEqual((c["fast"], c["explained"]), (1, 1))

    def test_a_slow_turn_is_not_counted_and_a_slow_clip_does_not_excuse_a_fast_turn(self):
        rates = track.clip_turn_rates(self.PROFILE)
        self.assertEqual(track.turn_causes(self.rows(["Run", "Run", "Run"], step=5.0), rates)[1]["fast"], 0)        # 50 deg/s
        self.assertEqual(track.turn_causes(self.rows(["Idle", "Idle"], step=90.0), rates)[1]["unexplained_count"], 1)   # Idle turns 5 deg/s

    def test_the_unexplained_list_is_capped_but_counted(self):
        c = track.turn_causes(self.rows(["Run"] * 40, step=90.0), track.clip_turn_rates(self.PROFILE), keep=3)[1]
        self.assertEqual((len(c["unexplained"]), c["unexplained_count"]), (3, 39))

    def test_a_row_without_a_yaw_or_a_time_is_skipped(self):
        rows = [ev(0.0, "mon", id=1, yaw=0.0, anim="Run"), ev(0.1, "mon", id=1, anim="Run"), {"e": "mon", "id": 1, "yaw": 90.0},
                ev(0.2, "mon", id=1, yaw="x"), ev(0.3, "mon", id=1, yaw=1.0, anim=None)]
        self.assertEqual(track.turn_causes(rows, {})[1]["fast"], 0)


class FollowTest(unittest.TestCase):
    def test_the_followed_position_is_nearer_the_hunter_than_the_last_report(self):
        rows = run_rows(10.0, 6.0, 4.0)
        speed = 6.0
        for k in range(5, 95):                                                   # 10 a second; the server follows with the lead its tracker gives
            t = k / 10.0
            last_report = math.floor(t * 4.0) / 4.0
            lead = 0.45 * math.tanh((t - last_report) / 0.45)
            rows.append(ev(t, "trk", x=100.0, y=100.0 + speed * (last_report + lead), lx=100.0, ly=100.0 + speed * last_report))
        rows.sort(key=lambda r: r["t"])
        e = track.tracking_error(rows)
        self.assertLess(e["followed_m"]["mean"], e["last_report_m"]["mean"] * 0.4)
        self.assertGreater(e["last_report_m"]["mean"], 0.6)

    def test_nothing_to_judge_by_gives_nothing(self):
        self.assertEqual(track.tracking_error([fifo(0.0, 0, 0)]), {})
        self.assertEqual(track.tracking_error(run_rows(2.0)), {})
