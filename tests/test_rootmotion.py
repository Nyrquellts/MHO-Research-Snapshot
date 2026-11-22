"""Check synthetic root-motion curves and endpoint handling."""

import unittest

from mho.rootmotion import resample_root_motion


class RootMotionTest(unittest.TestCase):
    def test_keys_between_samples_and_clip_endpoint_survive(self):
        result = resample_root_motion(
            0.93, step=0.25,
            x=[(0.0, 0.0), (0.36, 0.8), (0.93, 1.7)],
            y=[(0.0, 0.0), (0.93, 0.93)],
            yaw=[(0.0, 0.0), (0.86, 35.0), (0.93, 48.0)],
        )
        position = {row[0]: row[1:] for row in result["pos"]}
        angles = dict(result["yaw"])
        self.assertEqual(position[0.36], [0.8, 0.36, 0.0])
        self.assertEqual(position[0.93], [1.7, 0.93, 0.0])
        self.assertEqual(angles[0.86], 35.0)
        self.assertEqual(angles[0.93], 48.0)
        self.assertIn(0.25, position)

    def test_close_grid_and_key_times_are_merged(self):
        result = resample_root_motion(
            1.0, step=0.5, x=[(0.0, 0), (0.500001, 1), (1.0, 2)],
        )
        self.assertEqual([row[0] for row in result["pos"]], [0.0, 0.500001, 1.0])

    def test_constant_and_missing_tracks_are_omitted(self):
        result = resample_root_motion(1.0, x=[(0.0, 2), (1.0, 2)])
        self.assertEqual(result, {})

    def test_unsorted_keys_are_ordered_before_interpolation(self):
        result = resample_root_motion(1.0, step=0.5, yaw=[(1.0, 20), (0.0, 10)])
        self.assertEqual(result["yaw"], [[0.0, 10.0], [0.5, 15.0], [1.0, 20.0]])

    def test_rejects_invalid_duration_or_step(self):
        for duration, step in ((-1, 1), (1, 0), (1, float("nan")), (float("inf"), 1)):
            with self.subTest(duration=duration, step=step), self.assertRaises(ValueError):
                resample_root_motion(duration, step=step)


if __name__ == "__main__":
    unittest.main()
