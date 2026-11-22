import unittest

from mho.blackbox import motion_anomalies


def mon(t, mid, z, anim="Idle"):
    return {"e": "mon", "t": t, "id": mid, "x": 10.0, "y": 20.0, "z": z, "anim": anim, "hp": 100}


class DescentTest(unittest.TestCase):
    def test_a_cliff_walk_begins_where_the_monster_left_the_top_not_where_the_window_opened(self):
        rows = []
        for i in range(0, 50):                                                   # standing at the top for five seconds
            rows.append(mon(i * 0.1, 5, 50.0, "Idle"))
        for i in range(0, 51):                                                   # then 30 m down in five seconds while descending
            rows.append(mon(5.0 + i * 0.1, 5, 50.0 - 30.0 * i / 50.0, "Descend"))
        for i in range(1, 100):                                                  # then flat at the bottom
            rows.append(mon(10.0 + i * 0.1, 5, 20.0, "Idle"))
        walks = motion_anomalies.cliff_walks(rows)
        self.assertEqual(1, len(walks))
        walk = walks[0]
        self.assertEqual((5.0, 10.0, "Descend", ["Descend"]), (walk["t0"], walk["t1"], walk["anim"], walk["anims"]))
        self.assertEqual((50.0, 20.0, 30.0, 5.0), (walk["z0"], walk["z1"], walk["drop_m"], walk["descent_s"]))

    def test_a_teleport_is_no_cliff_walk(self):
        rows = [dict(mon(i * 0.1, 7, 80.0, "Lame"), x=10.0 + 0.2 * i) for i in range(0, 30)]                 # limping on the lip
        rows += [dict(mon(3.0 + i * 0.1, 7, 60.0, "Lame"), x=510.0 + 0.2 * i) for i in range(0, 30)]          # placed 500 m away and 20 m lower in 0.1 s
        self.assertEqual([], motion_anomalies.cliff_walks(rows))
        walked = [dict(mon(i * 0.1, 7, 80.0, "Idle"), x=10.0) for i in range(0, 10)]                         # the same drop walked: a second at the top,
        walked += [dict(mon(1.0 + j * 0.1, 7, 80.0 - 20.0 * min(j, 30) / 30.0, "Lame"), x=10.0 + 0.2 * j) for j in range(0, 51)]   # 3 s down, then flat
        walks = motion_anomalies.cliff_walks(walked)
        self.assertEqual((1, 20.0, 1.0, 4.0, 3.0), (len(walks), walks[0]["drop_m"], walks[0]["t0"], walks[0]["t1"], walks[0]["descent_s"]))


class RegionWalkEvidenceTest(unittest.TestCase):
    @staticmethod
    def limp(t0, seconds, mid=17, x=20.0, y=30.0, anim="Lame", step=0.1, drift=0.0):
        return [dict(mon(round(t0 + i * step, 3), mid, 80.0, anim), x=x + drift * i * step, y=y) for i in range(0, int(round(seconds / step)) + 1)]

    def test_a_limp_in_place_is_read_from_the_positions_and_headway_or_a_standing_clip_is_not(self):
        rows = self.limp(15.1, 4.3) + self.limp(25.0, 1.5, mid=18)                     # the synthetic stall, and one too short to count
        stalls = motion_anomalies.walks_in_place(rows)
        self.assertEqual([{"id": 17, "t": 15.1, "s": 4.3, "at": [20.0, 30.0], "anim": "Lame"}], stalls)
        self.assertEqual([], motion_anomalies.walks_in_place(self.limp(10.0, 6.0, drift=0.6)))   # 0.6 m a second: headway, not in place
        self.assertEqual([], motion_anomalies.walks_in_place(self.limp(10.0, 6.0, anim="Idle")))  # a monster that stands is not walking
        for standing in ("Move_Run_Prepare", "Move_Run_Start", "WalkEnd", "IdleToRun", "Shoot_Drunk", "Attack_NormalTrunBack", "Breath_Flame"):
            self.assertEqual([], motion_anomalies.walks_in_place(self.limp(10.0, 6.0, anim=standing)), standing)   # a wind-up, a stop, a word inside a word
        for walking in ("Move_Walk", "DyingWalk", "Move_LMG_Walk", "Move_Run", "Behavior_Walk", "TurnSprint", "RunAir", "Walk", "Run"):
            self.assertEqual(1, len(motion_anomalies.walks_in_place(self.limp(10.0, 6.0, anim=walking))), walking)  # a selection of walk labels
        broken = self.limp(10.0, 2.5) + self.limp(12.6, 2.5, x=26.0)                   # two stalls 6 m apart: two, longest first, at their own spots
        corpse = [dict(r, hp=0) for r in self.limp(10.0, 65.0, anim="DyingWalk")]       # the recorder keeps a dead monster's last loop clip
        self.assertEqual([], motion_anomalies.walks_in_place(corpse))
        dies = [dict(r, hp=0) if r["t"] >= 13.0 else r for r in self.limp(10.0, 8.0)]  # a limp in place that dies: the stall ends at death
        self.assertEqual([(10.0, 2.9)], [(w["t"], w["s"]) for w in motion_anomalies.walks_in_place(dies)])
        self.assertEqual([(2.5, 20.0), (2.5, 26.0)], [(w["s"], w["at"][0]) for w in motion_anomalies.walks_in_place(broken)])


class FlightEvidenceTest(unittest.TestCase):
    ROWS = [{"e": "mon", "t": 1.0, "id": 17, "z": 100.0, "anim": "Idle", "hp": 900},
            {"e": "mon", "t": 1.1, "id": 17, "z": 100.0, "anim": "FlyLiftStart", "hp": 900},
            {"e": "mon", "t": 1.6, "id": 17, "z": 104.5, "anim": "FlyLiftStart", "hp": 900},
            {"e": "mon", "t": 2.1, "id": 17, "z": 110.0, "anim": "Hovering", "hp": 900},
            {"e": "mon", "t": 2.2, "id": 33, "z": 50.0, "anim": "Hair", "hp": 100},
            {"e": "mon", "t": 3.0, "id": 17, "z": 100.2, "anim": "Landing", "hp": 900},
            {"e": "mon", "t": 4.0, "id": 17, "z": 100.2, "anim": "Move_Fly_F", "hp": 900},
            {"e": "mon", "t": 4.1, "id": 33, "z": 50.0, "anim": "Hovering", "hp": 0}]

    def test_airborne_names_are_recognized(self):
        for name, air in (("FlyLiftStart", True), ("Hovering", True), ("Move_Fly_F", True), ("Attack_AirFireBall", True), ("Flydown", True),
                          ("FlyDownSky", True), ("Landing", False), ("Hair", False), ("hairmaking", False), ("Walk", False), ("", False), (None, False)):
            self.assertEqual(air, motion_anomalies.is_air_clip(name), name)
        self.assertEqual(["attack", "air", "fire", "ball"], motion_anomalies.clip_words("Attack_AirFireBall2"))

    def test_the_stretches_and_their_rise(self):
        fl = motion_anomalies.flight(self.ROWS)
        self.assertEqual({"FlyLiftStart": 2, "Hovering": 1, "Move_Fly_F": 1}, fl["clips"])
        self.assertEqual((4, 2, 1, 10.0, 17, 1.1), (fl["air_rows"], fl["stretches"], fl["lifted"], fl["highest"], fl["highest_id"], fl["highest_t"]))
        none = motion_anomalies.flight([])
        self.assertEqual((0, 0, 0.0, None), (none["air_rows"], none["stretches"], none["highest"], none["highest_id"]))
