import math
import unittest

from mho.terrain import MapGrid


class TerrainTest(unittest.TestCase):
    def test_flat_plane_everywhere(self):
        g = MapGrid.flat_plane(0, 100, 0, 100, z=7.5)
        for x, y in [(0, 0), (50, 50), (100, 100), (12.3, 88.1)]:
            self.assertAlmostEqual(g.get_ground_z(x, y), 7.5)

    def test_out_of_bounds_clamps(self):
        g = MapGrid.flat_plane(0, 10, 0, 10, z=3.0)
        # Clamped to the edge, never extrapolated, always finite.
        for x, y in [(-100, -100), (999, 999), (-1, 5), (5, 50)]:
            z = g.get_ground_z(x, y)
            self.assertTrue(math.isfinite(z))
            self.assertAlmostEqual(z, 3.0)

    def test_bilinear_ramp(self):
        # Elevation == x. 2x2 grid over [0,10]x[0,10]: row0/row1 = [0,10].
        g = MapGrid.from_flat(0, 10, 0, 10, cols=2, rows=2, values=[0, 10, 0, 10])
        self.assertAlmostEqual(g.get_ground_z(0, 0), 0.0)
        self.assertAlmostEqual(g.get_ground_z(10, 5), 10.0)
        self.assertAlmostEqual(g.get_ground_z(5, 5), 5.0)
        self.assertAlmostEqual(g.get_ground_z(2.5, 9), 2.5)

    def test_diagonal_hill_no_nan(self):
        cols = rows = 33
        vals = []
        for r in range(rows):
            for c in range(cols):
                vals.append(math.sin(c / 4) * math.cos(r / 4) * 20)
        g = MapGrid.from_flat(-50, 50, -50, 50, cols, rows, vals)
        # Dense raycast sweep: every sample must be finite (the tick-safety invariant).
        for i in range(200):
            x = -60 + i * 0.6
            for j in range(0, 200, 7):
                y = -60 + j * 0.6
                self.assertTrue(math.isfinite(g.get_ground_z(x, y)))

    def test_non_finite_query_raises(self):
        g = MapGrid.flat_plane(0, 1, 0, 1)
        for bad in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(ValueError):
                g.get_ground_z(bad, 0.0)
            with self.assertRaises(ValueError):
                g.get_ground_z(0.0, bad)

    def test_construction_rejects_nan_and_bad_shape(self):
        with self.assertRaises(ValueError):
            MapGrid.from_flat(0, 1, 0, 1, 2, 2, [0, float("nan"), 0, 0])
        with self.assertRaises(ValueError):
            MapGrid.from_flat(0, 1, 0, 1, 2, 2, [0, 0, 0])  # wrong count
        with self.assertRaises(ValueError):
            MapGrid(0, 0, 0, 1, [[0, 0], [0, 0]])  # zero-width bounds

    def test_binary_roundtrip(self):
        g = MapGrid.from_flat(-5, 5, -3, 7, cols=4, rows=3, values=[float(i) for i in range(12)])
        g2 = MapGrid.from_bytes(g.to_bytes())
        self.assertEqual((g2.cols, g2.rows), (4, 3))
        self.assertAlmostEqual(g2.min_x, -5)
        self.assertAlmostEqual(g2.max_y, 7)
        for x in (-4, 0, 4):
            for y in (-2, 0, 6):
                self.assertAlmostEqual(g.get_ground_z(x, y), g2.get_ground_z(x, y), places=4)


if __name__ == "__main__":
    unittest.main()
