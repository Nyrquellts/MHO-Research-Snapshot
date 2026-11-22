import unittest

from mho.blackbox.ownership import Owner, classify, explain


class OwnershipTest(unittest.TestCase):
    def test_synthetic_application_modules(self):
        # Match the synthetic module names used by the examples.
        self.assertEqual(classify("SampleApp.exe"), Owner.APPLICATION)
        self.assertEqual(classify("SampleConnection.dll"), Owner.APPLICATION)
        self.assertEqual(classify("SampleEngine.dll"), Owner.ENGINE)
        self.assertEqual(classify("SampleEngineAction.dll"), Owner.ENGINE)
        self.assertEqual(classify("SampleEngineSystem.dll"), Owner.ENGINE)
        self.assertEqual(classify("ExampleDependency.dll"), Owner.DEPENDENCY)
        self.assertEqual(classify("ExampleDependencyBackup.dll"), Owner.DEPENDENCY)
        self.assertEqual(classify("ExampleDependencyTrace.dll"), Owner.DEPENDENCY)
        self.assertEqual(classify("sampleapp_recording.dll"), Owner.TOOLING)

    def test_paths_and_windows(self):
        self.assertEqual(classify(r"C:\Windows\System32\kernel32.dll"), Owner.WINDOWS)
        self.assertEqual(classify("ntdll.dll"), Owner.WINDOWS)
        self.assertEqual(classify("d3d9.dll"), Owner.WINDOWS)
        self.assertEqual(classify("api-ms-win-core-x-l1-1-0.dll"), Owner.WINDOWS)
        self.assertEqual(classify(r"D:\game\Bin32\SampleEngine.dll"), Owner.ENGINE)

    def test_third_party_and_unknown(self):
        self.assertEqual(classify("mss32.dll"), Owner.THIRD_PARTY)   # Miles Sound System
        self.assertEqual(classify("gfx.dll"), Owner.THIRD_PARTY)      # Scaleform
        self.assertEqual(classify("totally_unknown_thing.dll"), Owner.UNKNOWN)

    def test_tooling_beats_application_prefix(self):
        # sampleapp_recording matches the more specific tooling rule.
        owner, why = explain("sampleapp_recording.dll")
        self.assertEqual(owner, Owner.TOOLING)
        self.assertIn("sampleapp_recording", why)

    def test_explain_returns_reason(self):
        owner, why = explain("SampleEngine.dll")
        self.assertEqual(owner, Owner.ENGINE)
        self.assertTrue(why)


if __name__ == "__main__":
    unittest.main()
