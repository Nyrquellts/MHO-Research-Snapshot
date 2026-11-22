import os
import tempfile
import unittest

from mho.blackbox.events import EventType
from mho.blackbox.importers import etw
from mho.blackbox.ownership import Owner, classify
from mho.blackbox.causal import CausalGraph


# A faithful tracerpt XML export (Event Trace schema, default namespace). Nine kernel
# events exercising all three classification tiers: RenderingInfo text (most), a classic
# MOF GUID+opcode with NO RenderingInfo (E3 image), and an EventData-shape-only event
# (E8 thread). Times increase so rebasing to the first event is testable.
TRACERPT_XML = """<?xml version="1.0"?>
<Events xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <Event>
    <System>
      <Provider Name="MSNT_SystemTrace" Guid="{3d6fa8d0-fe05-11d0-9dda-00c04fd7ba7c}"/>
      <EventID>0</EventID><Opcode>1</Opcode><Task>1</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.0000000Z"/>
      <Execution ProcessID="100" ThreadID="200"/>
    </System>
    <EventData>
      <Data Name="ImageFileName">SampleApp.exe</Data>
      <Data Name="ProcessId">100</Data>
      <Data Name="ParentId">4</Data>
      <Data Name="CommandLine">SampleApp.exe --demo</Data>
    </EventData>
    <RenderingInfo Culture="en-US"><Opcode>Start</Opcode><Task>Process</Task></RenderingInfo>
  </Event>
  <Event>
    <System>
      <Provider Name="MSNT_SystemTrace" Guid="{9e814aad-3204-11d2-9a82-006008a86939}"/>
      <EventID>0</EventID><Opcode>10</Opcode><Task>2</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.1000000Z"/>
      <Execution ProcessID="100" ThreadID="200"/>
    </System>
    <EventData>
      <Data Name="ImageBase">0x10000000</Data>
      <Data Name="ImageFileName">\\Device\\HarddiskVolume2\\g\\SampleEngine.dll</Data>
      <Data Name="ProcessId">100</Data>
    </EventData>
    <RenderingInfo Culture="en-US"><Opcode>Load</Opcode><Task>Image</Task></RenderingInfo>
  </Event>
  <Event>
    <System>
      <Provider Name="MSNT_SystemTrace" Guid="{2cb15d1d-5fc1-11d2-abe1-00a0c911f518}"/>
      <EventID>0</EventID><Opcode>10</Opcode><Task>0</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.2000000Z"/>
      <Execution ProcessID="100" ThreadID="200"/>
    </System>
    <EventData>
      <Data Name="ImageBase">0x20000000</Data>
      <Data Name="ImageFileName">\\Device\\HarddiskVolume2\\g\\ExampleDependency.dll</Data>
    </EventData>
  </Event>
  <Event>
    <System>
      <Provider Name="MSNT_SystemTrace" Guid="{ae53722e-c863-11d2-8659-00c04fa321a1}"/>
      <EventID>0</EventID><Opcode>0</Opcode><Task>0</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.3000000Z"/>
      <Execution ProcessID="100" ThreadID="200"/>
    </System>
    <EventData>
      <Data Name="KeyName">\\REGISTRY\\MACHINE\\SOFTWARE\\SampleVendor\\Foo</Data>
      <Data Name="Status">3221225524</Data>
    </EventData>
    <RenderingInfo Culture="en-US"><Opcode>QueryValue</Opcode><Task>Registry</Task></RenderingInfo>
  </Event>
  <Event>
    <System>
      <Provider Name="MSNT_SystemTrace" Guid="{90cbdc39-4a3e-11d1-84f4-0000f80464e3}"/>
      <EventID>0</EventID><Opcode>64</Opcode><Task>0</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.4000000Z"/>
      <Execution ProcessID="100" ThreadID="200"/>
    </System>
    <EventData>
      <Data Name="FileName">\\Device\\NamedPipe\\SAMPLE_EVENT</Data>
      <Data Name="Status">0</Data>
    </EventData>
    <RenderingInfo Culture="en-US"><Opcode>Create</Opcode><Task>FileIo</Task></RenderingInfo>
  </Event>
  <Event>
    <System>
      <Provider Name="MSNT_SystemTrace" Guid="{9a280ac0-c8e0-11d1-84e2-00c04fb998a2}"/>
      <EventID>0</EventID><Opcode>12</Opcode><Task>0</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.5000000Z"/>
      <Execution ProcessID="100" ThreadID="200"/>
    </System>
    <EventData>
      <Data Name="daddr">192.0.2.23</Data>
      <Data Name="dport">9000</Data>
    </EventData>
    <RenderingInfo Culture="en-US"><Opcode>Connect</Opcode><Task>TcpIp</Task></RenderingInfo>
  </Event>
  <Event>
    <System>
      <Provider Name="MSNT_SystemTrace" Guid="{90cbdc39-4a3e-11d1-84f4-0000f80464e3}"/>
      <EventID>0</EventID><Opcode>67</Opcode><Task>0</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.6000000Z"/>
      <Execution ProcessID="100" ThreadID="200"/>
    </System>
    <EventData>
      <Data Name="FileName">\\Device\\HarddiskVolume2\\g\\config.xml</Data>
      <Data Name="Status">0</Data>
    </EventData>
    <RenderingInfo Culture="en-US"><Opcode>Read</Opcode><Task>FileIo</Task></RenderingInfo>
  </Event>
  <Event>
    <System>
      <Provider Name="Some.Manifest.Provider" Guid="{11111111-2222-3333-4444-555555555555}"/>
      <EventID>7</EventID><Opcode>0</Opcode><Task>0</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.7000000Z"/>
      <Execution ProcessID="100" ThreadID="777"/>
    </System>
    <EventData>
      <Data Name="TThreadId">777</Data>
      <Data Name="ProcessId">100</Data>
      <Data Name="StackBase">0x1000</Data>
    </EventData>
  </Event>
  <Event>
    <System>
      <Provider Name="MSNT_SystemTrace" Guid="{3d6fa8d0-fe05-11d0-9dda-00c04fd7ba7c}"/>
      <EventID>0</EventID><Opcode>2</Opcode><Task>1</Task>
      <TimeCreated SystemTime="2020-01-01T13:00:00.8660000Z"/>
      <Execution ProcessID="100" ThreadID="200"/>
    </System>
    <EventData>
      <Data Name="ImageFileName">SampleApp.exe</Data>
      <Data Name="ProcessId">100</Data>
      <Data Name="ExitStatus">3221225477</Data>
    </EventData>
    <RenderingInfo Culture="en-US"><Opcode>End</Opcode><Task>Process</Task></RenderingInfo>
  </Event>
</Events>
"""


class EtwImportTest(unittest.TestCase):
    def setUp(self):
        self.tl = etw.from_tracerpt_xml(TRACERPT_XML, label="broken", outcome="crashed")

    def test_event_types_in_order(self):
        got = [e.type for e in self.tl.events]
        self.assertEqual(got, [
            EventType.PROCESS_START, EventType.IMAGE_LOAD, EventType.IMAGE_LOAD,
            EventType.REG_QUERY, EventType.IPC, EventType.TCP_CONNECT,
            EventType.FILE_READ, EventType.THREAD_START, EventType.PROCESS_EXIT,
        ])

    def test_classification_tiers(self):
        self.assertEqual(self.tl.events[1].meta["classified_by"], "rendering")
        self.assertEqual(self.tl.events[2].meta["classified_by"], "guid")   # image, no RenderingInfo
        self.assertEqual(self.tl.events[7].meta["classified_by"], "shape")  # thread by EventData shape

    def test_field_extraction(self):
        reg = self.tl.events[3]
        self.assertTrue(reg.is_failure())                 # Status 0xC0000034
        self.assertIn("samplevendor", reg.object.lower())
        self.assertEqual(self.tl.events[5].object, "192.0.2.23:9000")
        exit_ev = self.tl.events[8]
        self.assertTrue(exit_ev.is_terminal() and exit_ev.is_failure())  # ExitStatus 0xC0000005

    def test_ownership_from_modules(self):
        self.assertEqual(classify(self.tl.events[1].module), Owner.ENGINE)   # SampleEngine.dll
        self.assertEqual(classify(self.tl.events[2].module), Owner.DEPENDENCY)     # ExampleDependency.dll

    def test_timestamps_rebased(self):
        self.assertAlmostEqual(self.tl.events[0].ts, 0.0, places=5)
        self.assertAlmostEqual(self.tl.events[1].ts, 0.1, places=4)
        self.assertAlmostEqual(self.tl.events[8].ts, 0.866, places=3)
        self.assertEqual(self.tl.events[0].pid, 100)

    def test_flows_into_causal(self):
        chain = CausalGraph(self.tl).why_exit()
        term = self.tl.terminal_event()
        self.assertEqual(term.type, EventType.PROCESS_EXIT)
        self.assertTrue(chain.steps)

    def test_utf16_file_roundtrip(self):
        # tracerpt commonly writes UTF-16LE with a BOM; from_file must sniff it.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "trace.xml")
            with open(p, "wb") as f:
                f.write(TRACERPT_XML.encode("utf-16"))
            tl = etw.from_file(p, label="broken")
        self.assertEqual(len(tl), 9)
        self.assertEqual(tl.events[8].type, EventType.PROCESS_EXIT)


if __name__ == "__main__":
    unittest.main()
