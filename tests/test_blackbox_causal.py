import unittest

from mho.blackbox.events import BlackboxEvent, EventType
from mho.blackbox.timeline import Timeline
from mho.blackbox.causal import CausalGraph
from mho.blackbox.diff import DiffEngine
from mho.blackbox.ownership import Owner


def _broken_crash_run():
    """Build a synthetic run that fails while reading its configuration."""
    tl = Timeline(label="broken", outcome="crashed")
    tl.add(BlackboxEvent(type=EventType.PROCESS_START, ts=0.0, pid=100, tid=10,
                         object="SampleApp.exe", result="SUCCESS"))
    tl.add(BlackboxEvent(type=EventType.IMAGE_LOAD, ts=0.5, pid=100,
                         object="SampleEngine.dll", module="SampleEngine.dll"))
    tl.add(BlackboxEvent(type=EventType.TCP_CONNECT, ts=0.7, pid=100, tid=10,
                         operation="connect", object="192.0.2.23:9000", result="SUCCESS"))
    tl.add(BlackboxEvent(type=EventType.LOG, ts=0.80, pid=100, tid=10, operation="log",
                         object="Initial connection succeeded", result="SUCCESS"))
    tl.add(BlackboxEvent(type=EventType.LOG, ts=0.85, pid=100, tid=10, operation="log",
                         object="Read sample configuration failed", result="FAILED"))
    tl.add(BlackboxEvent(type=EventType.EXCEPTION, ts=0.866, pid=100, tid=10,
                         operation="READ", object="SampleEngine.dll+0x120", result="0xC0000005",
                         module="SampleEngine.dll", rva=0x120,
                         stack=["SampleConnection.dll+0x210", "SampleConnection.dll+0x240",
                                "SampleEngine.dll+0x100", "SampleEngine.dll+0x120"]))
    return tl


class WhyExitTest(unittest.TestCase):
    def test_fault_site_and_owner(self):
        chain = CausalGraph(_broken_crash_run()).why_exit()
        text = "\n".join(s.text for s in chain.steps)
        self.assertIn("SampleEngine.dll+0x120", text)
        fault = [s for s in chain.steps if s.relation == "fault"][0]
        self.assertEqual(fault.owner, Owner.ENGINE)
        self.assertGreaterEqual(chain.confidence, 0.9)

    def test_call_path_attribution(self):
        chain = CausalGraph(_broken_crash_run()).why_exit()
        called = [s for s in chain.steps if s.relation == "called-from"]
        joined = "\n".join(s.text for s in called)
        self.assertIn("SampleConnection.dll", joined)
        self.assertIn(Owner.APPLICATION.value, joined)

    def test_proximate_failure_found(self):
        chain = CausalGraph(_broken_crash_run()).why_exit()
        prox = [s for s in chain.steps if s.relation == "proximate"]
        self.assertTrue(prox)
        self.assertIn("Read sample configuration failed", prox[0].text)

    def test_root_unknown_without_baseline(self):
        chain = CausalGraph(_broken_crash_run()).why_exit()
        root = chain.root()
        self.assertEqual(root.relation, "unknown")
        self.assertIn("UNKNOWN", root.text)
        self.assertFalse(root.observed)

    def test_root_from_baseline_diff(self):
        broken = _broken_crash_run()
        # a working run that gets past the same point without the failure/crash
        working = Timeline(label="working", outcome="connected")
        working.add(BlackboxEvent(type=EventType.PROCESS_START, ts=0.0, pid=100, tid=10,
                                  object="SampleApp.exe", result="SUCCESS"))
        working.add(BlackboxEvent(type=EventType.IMAGE_LOAD, ts=0.5, pid=100,
                                  object="SampleEngine.dll", module="SampleEngine.dll"))
        working.add(BlackboxEvent(type=EventType.TCP_CONNECT, ts=0.7, pid=100, tid=10,
                                  operation="connect", object="192.0.2.23:9000", result="SUCCESS"))
        working.add(BlackboxEvent(type=EventType.LOG, ts=0.80, pid=100, tid=10, operation="log",
                                  object="Initial connection succeeded",
                                  result="SUCCESS"))
        working.add(BlackboxEvent(type=EventType.LOG, ts=3.0, pid=100, tid=10, operation="log",
                                  object="still running", result="SUCCESS"))
        diff = DiffEngine(working, broken)
        chain = CausalGraph(broken).why_exit(baseline=diff)
        root = chain.root()
        self.assertEqual(root.relation, "root")
        self.assertIn("root cause vs working run", root.text)

    def test_no_events(self):
        chain = CausalGraph(Timeline(label="empty")).why_exit()
        self.assertTrue(chain.steps)  # a graceful "no events" step, not a crash


if __name__ == "__main__":
    unittest.main()
