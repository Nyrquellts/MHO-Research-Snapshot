import unittest

from mho.blackbox.events import EventType
from mho.blackbox.importers import procmon


PROCMON_CSV = (
    '"Time of Day","Process Name","PID","Operation","Path","Result","Detail","TID"\r\n'
    '"1:00:00.0000000 PM","SampleApp.exe","100","Process Start","","SUCCESS","","10"\r\n'
    '"1:00:00.1000000 PM","SampleApp.exe","100","Load Image","C:\\g\\SampleEngine.dll","SUCCESS","","10"\r\n'
    '"1:00:00.2000000 PM","SampleApp.exe","100","RegQueryValue","HKLM\\Software\\SampleVendor\\Foo","NAME NOT FOUND","Length: 16","10"\r\n'
    '"1:00:00.3000000 PM","SampleApp.exe","100","CreateFile","\\\\.\\pipe\\SAMPLE_EVENT","SUCCESS","","10"\r\n'
    '"1:00:00.4000000 PM","SampleApp.exe","100","Process Exit","","SUCCESS","","10"\r\n'
)

class ProcmonCsvTest(unittest.TestCase):
    def test_maps_operations_and_results(self):
        tl = procmon.from_csv(PROCMON_CSV, label="broken", outcome="exited-early")
        self.assertEqual(len(tl), 5)
        self.assertEqual(tl.events[0].type, EventType.PROCESS_START)
        self.assertEqual(tl.events[1].type, EventType.IMAGE_LOAD)
        self.assertEqual(tl.events[2].type, EventType.REG_QUERY)
        self.assertTrue(tl.events[2].is_failure())          # NAME NOT FOUND
        self.assertEqual(tl.events[3].type, EventType.IPC)   # pipe path -> IPC, not FILE
        self.assertEqual(tl.events[4].type, EventType.PROCESS_EXIT)

    def test_timestamps_rebased(self):
        tl = procmon.from_csv(PROCMON_CSV)
        self.assertAlmostEqual(tl.events[0].ts, 0.0, places=4)
        self.assertAlmostEqual(tl.events[4].ts, 0.4, places=4)


if __name__ == "__main__":
    unittest.main()
