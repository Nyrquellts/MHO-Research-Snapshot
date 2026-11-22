import unittest

from mho.blackbox.events import BlackboxEvent, EventType, parse_frame, normalize_object
from mho.blackbox.timeline import Timeline


class EventTest(unittest.TestCase):
    def test_parse_frame(self):
        self.assertEqual(parse_frame("SampleEngine.dll+0x120"), ("SampleEngine.dll", 0x120))
        self.assertEqual(parse_frame("SampleConnection.dll+0x210"), ("SampleConnection.dll", 0x210))
        self.assertEqual(parse_frame("some_symbol_no_offset"), (None, None))
        self.assertEqual(parse_frame(""), (None, None))

    def test_normalize_masks_volatile_bits(self):
        # addresses, trailing decimal ids and the user segment are masked so the
        # same thing aligns across two runs.
        self.assertEqual(normalize_object("SAMPLE_EVENT_BUFFER+1234"),
                         normalize_object("SAMPLE_EVENT_BUFFER+5678"))
        self.assertEqual(normalize_object("addr 0x0010035E"), normalize_object("addr 0x00ABCDEF"))
        self.assertEqual(normalize_object(r"C:\Users\SampleOne\x\y"),
                         normalize_object(r"C:\Users\SampleTwo\x\y"))
        # but real registry / file paths stay distinct
        self.assertNotEqual(normalize_object(r"HKLM\Software\SampleVendor\A"),
                            normalize_object(r"HKLM\Software\SampleVendor\B"))

    def test_is_failure(self):
        self.assertTrue(BlackboxEvent(result="NAME NOT FOUND").is_failure())
        self.assertTrue(BlackboxEvent(result="ACCESS DENIED").is_failure())
        self.assertTrue(BlackboxEvent(result="0xC0000005").is_failure())
        self.assertTrue(BlackboxEvent(type=EventType.EXCEPTION, result="").is_failure())
        self.assertFalse(BlackboxEvent(result="SUCCESS").is_failure())
        self.assertFalse(BlackboxEvent(result="").is_failure())
        self.assertFalse(BlackboxEvent(result="0x0").is_failure())

    def test_is_terminal(self):
        self.assertTrue(BlackboxEvent(type=EventType.PROCESS_EXIT).is_terminal())
        self.assertTrue(BlackboxEvent(type=EventType.EXCEPTION).is_terminal())
        self.assertTrue(BlackboxEvent(operation="TerminateProcess").is_terminal())
        self.assertFalse(BlackboxEvent(type=EventType.REG_QUERY).is_terminal())

    def test_semantic_key_is_type_aware(self):
        exc = BlackboxEvent(type=EventType.EXCEPTION, module="SampleEngine.dll", rva=0x120,
                            object="SampleEngine.dll+0x120")
        self.assertEqual(exc.semantic_key(), ("EXCEPTION", "sampleengine.dll", 0x120))
        img = BlackboxEvent(type=EventType.IMAGE_LOAD, object=r"C:\g\SampleEngine.dll",
                            module="SampleEngine.dll")
        self.assertEqual(img.semantic_key(), ("IMAGE_LOAD", "sampleengine.dll"))

    def test_roundtrip(self):
        ev = BlackboxEvent(type=EventType.EXCEPTION, source="dbglog", ts=0.87,
                           module="SampleEngine.dll", rva=0x120, result="0xC0000005",
                           stack=["a+0x1", "b+0x2"], meta={"regs": "eax=0"})
        ev2 = BlackboxEvent.from_dict(ev.to_dict())
        self.assertEqual(ev2.type, EventType.EXCEPTION)
        self.assertEqual(ev2.module, "SampleEngine.dll")
        self.assertEqual(ev2.rva, 0x120)
        self.assertEqual(ev2.stack, ["a+0x1", "b+0x2"])
        self.assertEqual(ev2.meta["regs"], "eax=0")


class TimelineTest(unittest.TestCase):
    def _tl(self):
        tl = Timeline(label="t", outcome="crashed")
        tl.add(BlackboxEvent(type=EventType.PROCESS_START, ts=0.0, pid=1))
        tl.add(BlackboxEvent(type=EventType.REG_QUERY, ts=0.2, pid=1,
                             operation="RegQueryValue", object="HKLM/x", result="NAME NOT FOUND"))
        tl.add(BlackboxEvent(type=EventType.EXCEPTION, ts=0.8, pid=1,
                             module="SampleEngine.dll", rva=0x120, result="0xC0000005"))
        return tl

    def test_filter_and_terminal(self):
        tl = self._tl()
        self.assertEqual(len(tl.filter(type=EventType.REG_QUERY)), 1)
        self.assertEqual(len(tl.filter(failures_only=True)), 2)  # reg miss + exception
        self.assertEqual(tl.filter(grep="sampleengine")[0].type, EventType.EXCEPTION)
        term = tl.terminal_event()
        self.assertEqual(term.type, EventType.EXCEPTION)

    def test_save_load_roundtrip(self):
        import json
        tl = self._tl()
        d = tl.to_dict()
        # survives a JSON encode/decode
        tl2 = Timeline.from_dict(json.loads(json.dumps(d)))
        self.assertEqual(len(tl2), 3)
        self.assertEqual(tl2.outcome, "crashed")
        self.assertEqual(tl2.terminal_event().module, "SampleEngine.dll")

    def test_seq_assigned_in_order(self):
        tl = self._tl()
        self.assertEqual([e.seq for e in tl.events], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
