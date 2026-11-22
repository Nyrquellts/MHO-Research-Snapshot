import unittest

from mho.blackbox.events import BlackboxEvent, EventType
from mho.blackbox.timeline import Timeline
from mho.blackbox.diff import DiffEngine
from mho.blackbox.ownership import Owner


def ev(t, ts, op="", obj="", result="", source="synthetic", pid=1, tid=10, **kw):
    return BlackboxEvent(type=t, ts=ts, operation=op, object=obj, result=result,
                         source=source, pid=pid, tid=tid, **kw)


class FlakyLaunchDiffTest(unittest.TestCase):
    """Compare a healthy sample run with one that exits early."""

    def _pair(self):
        working = Timeline(label="attempt-6", outcome="connected")
        for e in [
            ev(EventType.PROCESS_START, 0.0, obj="SampleApp.exe", result="SUCCESS"),
            ev(EventType.IMAGE_LOAD, 0.1, obj="SampleEngine.dll", module="SampleEngine.dll"),
            ev(EventType.IMAGE_LOAD, 0.2, obj="ExampleDependency.dll", module="ExampleDependency.dll"),
            ev(EventType.IPC, 0.3, op="OpenFileMapping", obj="SAMPLE_EVENT_BUFFER+1234", result="SUCCESS"),
            ev(EventType.LOG, 0.4, op="log", obj="Read initial configuration", result="SUCCESS"),
            ev(EventType.TCP_CONNECT, 0.5, op="connect", obj="192.0.2.23:9000", result="SUCCESS"),
            ev(EventType.LOG, 0.6, op="log", obj="Initial connection succeeded", result="SUCCESS"),
            ev(EventType.LOG, 5.0, op="log", obj="still running", result="SUCCESS"),
        ]:
            working.add(e)
        broken = Timeline(label="attempt-3", outcome="exited-early")
        for e in [
            ev(EventType.PROCESS_START, 0.0, obj="SampleApp.exe", result="SUCCESS"),
            ev(EventType.IMAGE_LOAD, 0.1, obj="SampleEngine.dll", module="SampleEngine.dll"),
            ev(EventType.IMAGE_LOAD, 0.2, obj="ExampleDependency.dll", module="ExampleDependency.dll"),
            ev(EventType.IPC, 0.3, op="OpenFileMapping", obj="SAMPLE_EVENT_BUFFER+5678", result="FAIL"),
            ev(EventType.PROCESS_EXIT, 0.4, obj="SampleApp.exe", result="SUCCESS"),
        ]:
            broken.add(e)
        return working, broken

    def test_first_divergence_is_the_mapping_failure(self):
        working, broken = self._pair()
        diff = DiffEngine(working, broken)
        div = diff.first_divergence()
        self.assertIsNotNone(div)
        self.assertEqual(div.kind, "result-diff")
        self.assertIn("sample_event", (div.broken.object or "").lower())
        self.assertEqual(div.working.result, "SUCCESS")
        self.assertEqual(div.broken.result, "FAIL")
        self.assertAlmostEqual(div.when, 0.3, places=6)

    def test_downstream_is_suppressed(self):
        working, broken = self._pair()
        diff = DiffEngine(working, broken)
        div = diff.first_divergence()
        # everything after the mapping failure (working's 4 later steps + the exit)
        self.assertGreaterEqual(diff.downstream_count(div), 4)

    def test_confidence_and_termination_link(self):
        working, broken = self._pair()
        diff = DiffEngine(working, broken)
        div = diff.first_divergence()
        self.assertTrue(div.leads_to_termination)
        self.assertGreaterEqual(div.confidence, 0.9)
        self.assertTrue(any("terminates" in e for e in div.evidence))

    def test_corroboration_raises_confidence(self):
        # the same SAMPLE_EVENT failure seen by a second sensor should raise confidence.
        working, broken = self._pair()
        broken.add(ev(EventType.IPC, 0.31, op="OpenFileMapping",
                      obj="SAMPLE_EVENT_BUFFER+5678", result="FAIL", source="clientlog"))
        diff = DiffEngine(working, broken)
        div = diff.first_divergence()
        self.assertTrue(any("corroborated" in e for e in div.evidence))


class MissingStepRootTest(unittest.TestCase):
    """A working-only root: the broken run never did something the working run did,
    before dying -- and a late working-only event is NOT mistaken for the root."""

    def test_working_only_before_death_is_the_root(self):
        working = Timeline(label="ok", outcome="connected")
        for e in [
            ev(EventType.PROCESS_START, 0.0, obj="SampleApp.exe", result="SUCCESS"),
            ev(EventType.IMAGE_LOAD, 0.1, obj="kernel32.dll", module="kernel32.dll"),
            ev(EventType.IMAGE_LOAD, 0.12, obj="SampleConnection.dll", module="SampleConnection.dll"),
            ev(EventType.TCP_CONNECT, 0.13, op="connect", obj="192.0.2.23:9000", result="SUCCESS"),
            ev(EventType.LOG, 2.0, op="log", obj="still running", result="SUCCESS"),
        ]:
            working.add(e)
        broken = Timeline(label="bad", outcome="crashed")
        for e in [
            ev(EventType.PROCESS_START, 0.0, obj="SampleApp.exe", result="SUCCESS"),
            ev(EventType.IMAGE_LOAD, 0.1, obj="kernel32.dll", module="kernel32.dll"),
            ev(EventType.PROCESS_EXIT, 0.15, obj="SampleApp.exe", result="SUCCESS"),
        ]:
            broken.add(e)
        diff = DiffEngine(working, broken)
        div = diff.first_divergence()
        self.assertEqual(div.kind, "working-only")
        target = (div.working.module or div.working.object or "").lower()
        self.assertIn("sampleconnection", target)
        # the late (t=2.0) working-only "still running" must not win.
        self.assertLessEqual(div.when, 0.15)


class OwnerBreakdownTest(unittest.TestCase):
    def test_tail_owner_breakdown(self):
        broken = Timeline(label="bad", outcome="crashed")
        broken.add(ev(EventType.IMAGE_LOAD, 0.1, obj="kernel32.dll", module="kernel32.dll"))
        broken.add(ev(EventType.IMAGE_LOAD, 0.8, obj="SampleEngine.dll", module="SampleEngine.dll"))
        broken.add(ev(EventType.EXCEPTION, 0.86, module="SampleEngine.dll", rva=0x120,
                      result="0xC0000005"))
        diff = DiffEngine(Timeline(label="ok"), broken)
        rows = diff.owner_breakdown(window=0.2)   # last 200ms
        owners = {o for o, _, _ in rows}
        self.assertIn(Owner.ENGINE, owners)


if __name__ == "__main__":
    unittest.main()
