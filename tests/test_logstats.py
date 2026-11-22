"""Offline diagnostics tests with synthetic log records."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

from mho import logstats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import log_stats  # noqa: E402

AI_1 = "2020-01-01 16:42:10 - Info - HuntDirector: hunt 101 (session 1): monster AI stopped after 443 steps: 164.6 Hz, 2 late (over 1.5 periods), the longest gap 14.5 ms, a step took 0.060 ms on average, 7.5 ms at most"
AI_2 = "2020-01-01 16:42:11 - Info - HuntDirector: hunt 102 (session 4): monster AI stopped after 462 steps: 164.6 Hz, 1 late (over 1.5 periods), the longest gap 11.2 ms, a step took 0.008 ms on average, 0.1 ms at most"
ZONE_MS = "2020-01-01 16:42:10 - Info - ZoneHost: 192.0.2.5:50001 zone 101: ending (Completed): 101 Completed: Loading 0.3 ms, Initializing 201.5 ms, Spawning 127.1 ms, Active 2.6 s, Cleanup 0.8 ms"
ZONE_GONE = "2020-01-01 16:53:03 - Info - ZoneHost: 192.0.2.5:50002 zone 103: ending (Disconnected): 103 Disconnected: Loading 0 ms, Initializing 78.3 ms, Spawning 12.9 ms, Active 4.7 s, Cleanup 0 ms"
HEALTH_1 = ("2020-01-01 16:52:44 - Info - ServerHealth: health: 12 connection(s), 1326 town session(s), 0 hunt(s), 6 part(ies), 0 field world(s), 0 zone(s) open | "
            "22 threads, 498 handles, 516 MB working set, 408 MB managed, gc 619/12/3 | up 611 s")
HEALTH_2 = ("2020-01-01 17:01:44 - Info - ServerHealth: health: 2 connection(s), 1500 town session(s), 1 hunt(s), 0 part(ies), 0 field world(s), 1 zone(s) open | "
            "24 threads, 510 handles, 600 MB working set, 450 MB managed, gc 900/20/4 | up 1150 s")
ERROR = "2020-01-01 16:52:45 - Error - AsyncEventServer: ProcessReceive - Client is null"
HEX_ROW = "00000000   00 01 02 03   ...."
TRACE = "2020-01-01 16:52:44 - Trace - CharacterManager: 192.0.2.5:50003 ListProfiles"
LOG = [AI_1, AI_2, ZONE_MS, ZONE_GONE, HEALTH_1, HEALTH_2, ERROR, "   at Some.Stack.Frame()", "Header:", HEX_ROW, TRACE]


class TransportErrorsTest(unittest.TestCase):
    """The Error entries the transport's own code and the consumers of its events write: a connection that arrives or ends out of order, an accept or a receive that fails."""
    LOG = "\n".join([
        "2020-01-01 16:52:44 - Info - WorldTransportServer: [192.0.2.10:50000] accepted 127.0.0.1:50000 (1 open)",
        "2020-01-01 16:52:45 - Error - WorldTransportServer: [192.0.2.10:50000] accept failed (1 in a row): SocketException: no buffer space",
        "   at System.Net.Sockets.Socket.AcceptAsync()",
        "2020-01-01 16:52:46 - Error - ZoneConsumer: 127.0.0.1:50000 Disconnected client does not exist in lookup",
        "2020-01-01 16:52:47 - Error - SessionConsumer: 127.0.0.1:50001 Client does not exist in lookup",
        "2020-01-01 16:52:48 - Error - LoginHandler: 127.0.0.1:50002 Invalid Password",
        "2020-01-01 16:52:49 - Error - Client: 127.0.0.1:50003 unreadable stream -- closing the connection",
        "2020-01-01 16:52:50 - Info - Something: WorldTransportServer is fine",
    ])

    def test_the_transport_and_its_consumers_errors_are_found_and_nothing_else(self):
        found = logstats.transport_errors(self.LOG)
        self.assertEqual(len(found), 3)
        self.assertTrue(found[0].startswith("2020-01-01 16:52:45"))
        self.assertTrue(all(" - Error - " in entry for entry in found))

    def test_the_answers_to_a_hostile_client_are_not_the_transports(self):
        for entry in ("2020-01-01 16:52:48 - Error - LoginHandler: 127.0.0.1:1 Invalid Password",
                      "2020-01-01 16:52:49 - Error - Client: 127.0.0.1:2 invalid input record",
                      "2020-01-01 16:52:49 - Error - JoinHandler: 127.0.0.1:3 missing sample record"):
            self.assertEqual(logstats.transport_errors(entry + "\n"), [], entry)

    def test_a_consumer_answering_a_hostile_packet_is_not_the_transports(self):
        # Synthetic entries for rejected or unknown input.
        for entry in ("2020-01-01 18:45:27 - Error - SessionConsumer: 127.0.0.1:61213 System.IO.EndOfStreamException: Unable to read beyond the end of the stream.",
                      "2020-01-01 18:45:27 - Error - SessionConsumer: 127.0.0.1:61216 System.NullReferenceException: Object reference not set to an instance of an object.",
                      "2020-01-01 18:45:27 - Error - SessionConsumer: PACKET ERROR:127.0.0.1:61213",
                      "2020-01-01 18:45:28 - Error - SessionConsumer: PACKET UNHANDLED:",
                      "2020-01-01 18:45:28 - Error - ZoneConsumer: PACKET UNHANDLED:"):
            self.assertEqual(logstats.transport_errors(entry + "\n"), [], entry)

    def test_a_carriage_return_does_not_hide_an_entry_and_is_not_kept(self):
        entry = "2020-01-01 16:52:46 - Error - SessionConsumer: 127.0.0.1:1 Client does not exist in lookup"
        self.assertEqual(logstats.transport_errors(entry + "\r\n"), [entry])

    def test_an_info_or_debug_entry_of_the_transport_is_not_an_error(self):
        self.assertEqual(logstats.transport_errors("2020-01-01 16:52:46 - Debug - WorldTransportServer: [192.0.2.10:50000] closed 127.0.0.1:1 (0 open)\n"), [])

    def test_a_log_without_any_is_empty(self):
        self.assertEqual(logstats.transport_errors(""), [])


class PercentileTest(unittest.TestCase):
    def test_nearest_rank(self):
        values = [float(i) for i in range(1, 101)]
        self.assertEqual(logstats.percentile(values, 50), 50.0)
        self.assertEqual(logstats.percentile(values, 95), 95.0)
        self.assertEqual(logstats.percentile(values, 99), 99.0)
        self.assertEqual(logstats.percentile(values, 100), 100.0)

    def test_the_order_of_the_input_does_not_matter(self):
        self.assertEqual(logstats.percentile([5.0, 1.0, 3.0], 50), 3.0)

    def test_one_value_is_every_percentile_and_none_is_zero(self):
        self.assertEqual(logstats.percentile([7.0], 99), 7.0)
        self.assertEqual(logstats.percentile([], 50), 0.0)
        self.assertEqual(logstats.spread([])["n"], 0)

    def test_spread_says_how_many_and_the_extremes(self):
        s = logstats.spread([1.0, 2.0, 3.0, 4.0])
        self.assertEqual((s["n"], s["min"], s["p50"], s["max"]), (4, 1.0, 2.0, 4.0))


class AnalyseTest(unittest.TestCase):
    def setUp(self):
        self.stats = logstats.analyse(LOG)

    def test_only_entries_are_counted_by_level_and_the_span_is_the_first_to_the_last(self):
        self.assertEqual(self.stats["entries"], 8)                                     # the stack line, the dump's header and its hex row belong to the entry above
        self.assertEqual(self.stats["levels"], {"Info": 6, "Error": 1, "Trace": 1})
        self.assertEqual((self.stats["first"], self.stats["last"]), ("2020-01-01 16:42:10", "2020-01-01 16:52:44"))

    def test_the_ai_clock_of_every_hunt(self):
        ai = self.stats["ai"]
        self.assertEqual((ai["hunts"], ai["steps"], ai["late"]), (2, 905, 3))
        self.assertAlmostEqual(ai["late_share"], 3 / 905, places=6)
        self.assertEqual(ai["longest_gap_ms"]["max"], 14.5)
        self.assertEqual(ai["step_avg_ms"]["min"], 0.008)
        self.assertEqual(ai["step_max_ms"]["max"], 7.5)
        self.assertEqual(ai["hz"]["p50"], 164.6)

    def test_the_stages_of_every_zone_in_milliseconds_whatever_unit_the_server_wrote(self):
        z = self.stats["zones"]
        self.assertEqual(z["ended"], 2)
        self.assertEqual(z["exits"], {"Completed": 1, "Disconnected": 1})
        self.assertEqual(z["stages_ms"]["Active"]["min"], 2600.0)                      # "2.6 s"
        self.assertEqual(z["stages_ms"]["Active"]["max"], 4700.0)
        self.assertEqual(z["stages_ms"]["Initializing"]["max"], 201.5)
        self.assertEqual(z["stages_ms"]["Loading"]["min"], 0.0)                        # "0 ms"
        self.assertEqual(z["stages_ms"]["Cleanup"]["n"], 2)

    def test_the_health_series_and_where_it_began_and_ended(self):
        h = self.stats["health"]
        self.assertEqual(h["snapshots"], 2)
        self.assertEqual((h["first"]["working_set_mb"], h["last"]["working_set_mb"]), (516, 600))
        self.assertEqual((h["first"]["uptime_s"], h["last"]["uptime_s"]), (611, 1150))
        self.assertEqual((h["first"]["gc0"], h["last"]["gc2"]), (619, 4))
        self.assertEqual(h["threads"]["max"], 24.0)
        self.assertEqual(h["town_sessions"]["max"], 1500.0)

    def test_a_log_with_nothing_to_measure_is_zeroes_not_a_crash(self):
        empty = logstats.analyse(["", "no timestamp here", HEX_ROW])
        self.assertEqual(empty["entries"], 0)
        self.assertEqual(empty["ai"]["hunts"], 0)
        self.assertEqual(empty["ai"]["late_share"], 0.0)
        self.assertEqual(empty["health"]["snapshots"], 0)
        self.assertEqual(empty["health"]["first"], None)
        self.assertTrue(logstats.render(empty))                                        # and it can still be printed

    def test_a_line_that_says_it_but_not_in_the_servers_words_is_not_a_measurement(self):
        odd = "2020-01-01 16:42:10 - Info - HuntDirector: hunt 1 (session 1): monster AI stopped after many steps"
        self.assertEqual(logstats.analyse([odd])["ai"]["hunts"], 0)


class RenderTest(unittest.TestCase):
    def test_the_lines_carry_the_numbers_a_person_looks_for(self):
        text = "\n".join(logstats.render(logstats.analyse(LOG), "x.log"))
        self.assertIn("log x.log", text)
        self.assertIn("8 entries", text)
        self.assertIn("2 hunts, 905 steps, 3 late", text)
        self.assertIn("2 ended (1 Completed, 1 Disconnected)", text)
        self.assertIn("working set 516 -> 600 MB", text)
        self.assertIn("p99", text)


class FileTest(unittest.TestCase):
    def test_a_file_is_read_as_utf8_and_a_bad_byte_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.txt")
            with open(path, "wb") as f:
                f.write((AI_1 + "\r\n").encode("utf-8") + b"\xff\xfe not utf-8\n" + (ERROR + "\n").encode("utf-8"))
            lines = list(logstats.read_lines(path))
        self.assertEqual(lines[0], AI_1)                                               # the CR of a Windows line end is gone
        self.assertEqual(logstats.analyse(lines)["entries"], 2)

    def test_the_script_prints_and_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, out = os.path.join(tmp, "log.txt"), os.path.join(tmp, "stats.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(LOG) + "\n")
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(log_stats.main([path, "--json", out]), 0)
            self.assertIn("monster AI: 2 hunts", printed.getvalue())
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["ai"]["hunts"], 2)

    def test_a_log_that_is_not_there_is_exit_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(log_stats.main([os.path.join(tempfile.gettempdir(), "no-such-server-log-3f9a.txt")]), 2)


if __name__ == "__main__":
    unittest.main()
