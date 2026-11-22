import unittest

from mho.blackbox.events import BlackboxEvent, EventType
from mho.blackbox.timeline import Timeline
from mho.blackbox.diff import DiffEngine
from mho.blackbox.causal import CausalGraph
from mho.blackbox import report


def _pair():
    working = Timeline(label="ok", outcome="connected")
    broken = Timeline(label="bad", outcome="crashed")
    for tl, res in ((working, "SUCCESS"), (broken, "FAIL")):
        tl.add(BlackboxEvent(type=EventType.PROCESS_START, ts=0.0, pid=1, object="SampleApp.exe", result="SUCCESS"))
        tl.add(BlackboxEvent(type=EventType.IPC, ts=0.3, pid=1, operation="OpenFileMapping",
                             object="SAMPLE_EVENT_BUFFER+1", result=res))
    working.add(BlackboxEvent(type=EventType.LOG, ts=1.0, pid=1, object="running", result="SUCCESS"))
    broken.add(BlackboxEvent(type=EventType.EXCEPTION, ts=0.9, pid=1, module="SampleEngine.dll",
                             rva=0x120, result="0xC0000005", operation="READ",
                             object="SampleEngine.dll+0x120",
                             stack=["SampleConnection.dll+0x210", "SampleEngine.dll+0x120"]))
    return working, broken


class ReportTest(unittest.TestCase):
    def test_first_divergence_render(self):
        w, b = _pair()
        text = report.render_first_divergence(DiffEngine(w, b))
        self.assertIn("FIRST DIVERGENCE", text)
        self.assertIn("SAMPLE_EVENT", text.upper())
        self.assertIn("Confidence", text)
        self.assertIn("Downstream", text)

    def test_why_render(self):
        _, b = _pair()
        chain = CausalGraph(b).why_exit()
        text = report.render_why(chain)
        self.assertIn("WHY THE PROCESS ENDED", text)
        self.assertIn("SampleEngine.dll+0x120", text)
        self.assertIn("UNKNOWN", text)   # no baseline -> root is honest UNKNOWN

    def test_report_dict_schema(self):
        w, b = _pair()
        d = report.report_dict(w, b)
        self.assertEqual(d["schema"], "nyr-blackbox-report/1")
        self.assertIsNotNone(d["first_divergence"])
        self.assertTrue(d["why"]["steps"])
        self.assertTrue(d["owner_breakdown"])

    def test_render_full_runs(self):
        w, b = _pair()
        text = report.render_full(w, b)
        self.assertIn("FIRST DIVERGENCE", text)
        self.assertIn("OWNER BREAKDOWN", text)
        self.assertIn("WHY THE PROCESS ENDED", text)


if __name__ == "__main__":
    unittest.main()
