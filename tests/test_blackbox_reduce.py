import gc
import os
import tempfile
import tracemalloc
import unittest

from mho.blackbox.events import BlackboxEvent, EventType
from mho.blackbox.timeline import Timeline
from mho.blackbox.reduce import HierarchicalReducer, ReductionConfig, reduce_events, reduce_capture
from mho.blackbox.diff import DiffEngine
from mho.blackbox.causal import CausalGraph
from mho.blackbox.importers import procmon, etw


def synth(n_noise, crash=True, reg_fail=False):
    """A synthetic capture: lifecycle + a flood of repetitive successful reads + a few
    high-value events. Mirrors the real shape (millions of quiet reads, one crash)."""
    yield BlackboxEvent(type=EventType.PROCESS_START, source="etw", ts=0.0, pid=100, tid=10,
                        object="SampleApp.exe", result="SUCCESS")
    yield BlackboxEvent(type=EventType.IMAGE_LOAD, source="etw", ts=0.1, pid=100,
                        object="SampleEngine.dll", module="SampleEngine.dll")
    yield BlackboxEvent(type=EventType.IMAGE_LOAD, source="etw", ts=0.2, pid=100,
                        object="ExampleDependency.dll", module="ExampleDependency.dll")
    yield BlackboxEvent(type=EventType.TCP_CONNECT, source="etw", ts=0.5, pid=100, tid=10,
                        operation="connect", object="192.0.2.23:9000", result="SUCCESS")
    files = [f"C:/g/data/file{i}.arc" for i in range(8)]
    for k in range(n_noise):
        yield BlackboxEvent(type=EventType.FILE_READ, source="etw", ts=1.0 + k * 1e-4, pid=100,
                            tid=10, operation="Read", object=files[k % 8], result="SUCCESS")
    if reg_fail:
        yield BlackboxEvent(type=EventType.REG_QUERY, source="etw", ts=8.0, pid=100, tid=10,
                            operation="QueryValue",
                            object="HKLM/Software/SampleVendor/Foo", result="0xC0000034")
    if crash:
        yield BlackboxEvent(type=EventType.LOG, source="etw", ts=8.5, pid=100, tid=10,
                            operation="log", object="Read sample configuration failed",
                            result="FAILED")
        yield BlackboxEvent(type=EventType.EXCEPTION, source="dbglog", ts=8.66, pid=100, tid=10,
                            operation="READ", object="SampleEngine.dll+0x120", result="0xC0000005",
                            module="SampleEngine.dll", rva=0x120,
                            stack=["SampleConnection.dll+0x210", "SampleEngine.dll+0x120"])


class ReducerUnitTest(unittest.TestCase):
    def test_collapses_success_keeps_highvalue(self):
        events = list(synth(100, crash=True, reg_fail=True))
        # add one FAILED read to prove failures are never collapsed
        events.insert(6, BlackboxEvent(type=EventType.FILE_READ, source="etw", ts=1.5, pid=100,
                                       tid=10, operation="Read", object="C:/g/bad.arc",
                                       result="ACCESS DENIED"))
        # windows off, so the collapse count is exact (no reads spared as raw context)
        red = reduce_events(iter(events), config=ReductionConfig(after_window=0, tail_window=0))
        r = red.meta["reduction"]
        self.assertEqual(r["seen"], len(events))
        self.assertEqual(r["signatures"], 8)          # 8 distinct success files
        self.assertEqual(r["collapsed"], 100)         # the 100 successful reads
        # high-value survivors are all present
        types = [e.type for e in red.events]
        self.assertIn(EventType.EXCEPTION, types)
        self.assertIn(EventType.PROCESS_START, types)
        self.assertIn(EventType.REG_QUERY, types)     # the failed reg query (is_failure)
        self.assertTrue(any(e.is_failure() and "bad.arc" in e.object for e in red.events))
        # a signature rep carries its collapsed count
        reps = [e for e in red.events if e.meta.get("collapsed")]
        self.assertEqual(len(reps), 8)
        self.assertTrue(all(rep.meta["collapsed"] > 0 for rep in reps))

    def test_tail_window_preserves_lead_up(self):
        cfg = ReductionConfig(tail_window=32, after_window=8)
        events = [BlackboxEvent(type=EventType.UNKNOWN, source="etw", ts=float(i), operation="x",
                                object=f"q{i}") for i in range(40)]
        events.append(BlackboxEvent(type=EventType.EXCEPTION, source="dbglog", ts=99.0,
                                    module="SampleEngine.dll", rva=0x120, result="0xC0000005"))
        red = reduce_events(iter(events), config=cfg)
        # 32-event window before the exception + the exception itself
        self.assertEqual(len(red), 33)
        self.assertEqual(red.events[-1].type, EventType.EXCEPTION)

    def test_working_set_is_bounded(self):
        # feed a big stream; the kept set must stay small (bounded), not grow with input
        r = HierarchicalReducer(ReductionConfig())
        for ev in synth(50000, crash=True, reg_fail=True):
            r.feed(ev)
        red = r.finalize()
        self.assertEqual(red.meta["reduction"]["seen"], 50007)  # 4 lifecycle + 50000 + reg + log + exc
        self.assertLess(len(red), 200)               # lifecycle + 8 sigs + windows, not 50k


class StreamingEquivalenceTest(unittest.TestCase):
    def test_procmon_stream_matches_whole_parse(self):
        csv_text = (
            '"Time of Day","Process Name","PID","Operation","Path","Result","Detail","TID"\r\n'
            '"1:00:00.0000000 PM","SampleApp.exe","100","Process Start","","SUCCESS","","10"\r\n'
            '"1:00:00.1000000 PM","SampleApp.exe","100","Load Image","C:\\g\\SampleEngine.dll","SUCCESS","","10"\r\n'
            '"1:00:00.2000000 PM","SampleApp.exe","100","RegQueryValue","HKLM\\x","NAME NOT FOUND","","10"\r\n'
            '"1:00:00.3000000 PM","SampleApp.exe","100","CreateFile","\\\\.\\pipe\\SAMPLE_EVENT","SUCCESS","","10"\r\n'
        )
        whole = procmon.from_csv(csv_text)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.csv")
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(csv_text)
            streamed = list(procmon.stream_file(p))
        self.assertEqual([e.type for e in whole.events], [e.type for e in streamed])
        self.assertEqual([e.object for e in whole.events], [e.object for e in streamed])
        self.assertEqual([e.result for e in whole.events], [e.result for e in streamed])

    def test_etw_stream_matches_whole_parse(self):
        xml = (
            '<?xml version="1.0"?>\n<Events xmlns="http://schemas.microsoft.com/win/2004/08/events/event">\n'
            '<Event><System><Provider Guid="{3d6fa8d0-fe05-11d0-9dda-00c04fd7ba7c}"/>'
            '<Opcode>1</Opcode><TimeCreated SystemTime="2020-01-01T13:00:00.0000000Z"/>'
            '<Execution ProcessID="100" ThreadID="10"/></System>'
            '<EventData><Data Name="ImageFileName">SampleApp.exe</Data><Data Name="ProcessId">100</Data>'
            '<Data Name="ParentId">4</Data></EventData>'
            '<RenderingInfo><Opcode>Start</Opcode><Task>Process</Task></RenderingInfo></Event>\n'
            '<Event><System><Provider Guid="{2cb15d1d-5fc1-11d2-abe1-00a0c911f518}"/>'
            '<Opcode>10</Opcode><TimeCreated SystemTime="2020-01-01T13:00:00.1000000Z"/>'
            '<Execution ProcessID="100" ThreadID="10"/></System>'
            '<EventData><Data Name="ImageBase">0x1</Data><Data Name="ImageFileName">SampleEngine.dll</Data></EventData>'
            '</Event>\n</Events>\n'
        )
        whole = etw.from_tracerpt_xml(xml)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.xml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(xml)
            streamed = list(etw.iter_tracerpt_file(p))
        self.assertEqual([e.type for e in whole.events], [e.type for e in streamed])
        self.assertEqual([e.object for e in whole.events], [e.object for e in streamed])


class SameConclusionTest(unittest.TestCase):
    """The Definition of Done: reduction must reach the SAME causal conclusion."""

    def test_why_exit_matches_full(self):
        full = Timeline()
        for ev in synth(20000, crash=True):
            full.add(ev)
        reduced = reduce_events(synth(20000, crash=True))
        full_why = CausalGraph(full).why_exit()
        red_why = CausalGraph(reduced).why_exit()
        fault_full = [s for s in full_why.steps if s.relation == "fault"][0]
        fault_red = [s for s in red_why.steps if s.relation == "fault"][0]
        self.assertEqual(fault_full.text, fault_red.text)
        self.assertIn("SampleEngine.dll+0x120", fault_red.text)
        prox = [s for s in red_why.steps if s.relation == "proximate"]
        self.assertTrue(prox and "Read sample configuration failed" in prox[0].text)

    def test_first_divergence_matches_full(self):
        # full diff stays under the DiffEngine size guard (raw diffing is O(n*m));
        # 3000 noise events is plenty to exercise reduction, and the guard's whole point
        # is that you reduce before diffing anything larger.
        full_w = Timeline(); [full_w.add(e) for e in synth(3000, crash=False, reg_fail=False)]
        full_b = Timeline(); [full_b.add(e) for e in synth(3000, crash=True, reg_fail=True)]
        red_w = reduce_events(synth(3000, crash=False, reg_fail=False))
        red_b = reduce_events(synth(3000, crash=True, reg_fail=True))
        full_div = DiffEngine(full_w, full_b).first_divergence()
        red_div = DiffEngine(red_w, red_b).first_divergence()
        self.assertIn("samplevendor", full_div.description().lower())
        self.assertIn("samplevendor", red_div.description().lower())
        self.assertEqual(full_div.kind, red_div.kind)


class PeakMemoryTest(unittest.TestCase):
    """The other half of the DoD: materially lower peak memory."""

    def test_reduced_peak_far_below_full(self):
        N = 120000
        gc.collect()
        tracemalloc.start()
        full = Timeline()
        for ev in synth(N, crash=True):
            full.add(ev)
        _, full_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        kept_full = len(full)
        del full
        gc.collect()

        tracemalloc.start()
        reduced = reduce_events(synth(N, crash=True))
        _, red_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        self.assertGreater(kept_full, N)                 # full really held everything
        self.assertLess(len(reduced), 200)               # reduced held a bounded set
        self.assertLess(red_peak, full_peak / 3)         # materially lower peak memory


class ReduceCaptureTest(unittest.TestCase):
    def test_reduce_capture_streams_from_disk(self):
        csv_text = ('"Time of Day","Process Name","PID","Operation","Path","Result","Detail","TID"\r\n'
                    '"1:00:00.0000000 PM","SampleApp.exe","100","Process Start","","SUCCESS","","10"\r\n')
        for i in range(200):
            csv_text += f'"1:00:0{0}.{i:07d} PM","SampleApp.exe","100","ReadFile","C:\\g\\f{i%4}.arc","SUCCESS","","10"\r\n'
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.csv")
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(csv_text)
            red = reduce_capture(p, "procmon-csv", label="broken")
        self.assertTrue(red.meta["reduction"]["collapsed"] >= 190)  # reads collapsed
        self.assertTrue(red.meta.get("streamed"))


class DiffScaleTest(unittest.TestCase):
    def test_myers_scales_on_large_similar(self):
        # 8000 vs 8000 -- difflib would build a 64M-cell table; Myers aligns in O(n+d)
        # because the runs are near-identical (edit distance ~0). One injected failure.
        a, b = Timeline(label="ok"), Timeline(label="bad")
        for i in range(8000):
            a.add(BlackboxEvent(type=EventType.FILE_READ, ts=float(i), operation="Read",
                                object=f"f{i % 50}", result="SUCCESS"))
            res = "NAME NOT FOUND" if i == 4000 else "SUCCESS"
            b.add(BlackboxEvent(type=EventType.FILE_READ, ts=float(i), operation="Read",
                                object=f"f{i % 50}", result=res))
        div = DiffEngine(a, b).first_divergence()
        self.assertIsNotNone(div)
        self.assertEqual(div.kind, "result-diff")   # finds the single injected failure


if __name__ == "__main__":
    unittest.main(verbosity=2)
