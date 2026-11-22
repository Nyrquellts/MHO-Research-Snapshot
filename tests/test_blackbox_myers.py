import difflib
import random
import unittest

from mho.blackbox.myersdiff import intern_two, myers_opcodes


def apply_ops(a, b, ops):
    """Reconstruct b from a using the opcodes -- the invariant a correct diff must hold."""
    out = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            out.extend(a[i1:i2])
        elif tag == "insert":
            out.extend(b[j1:j2])
        # delete: contributes nothing
    return out


class MyersTest(unittest.TestCase):
    def test_reconstructs_b_and_equal_blocks_match(self):
        rnd = random.Random(1234)
        for _ in range(300):
            a = [rnd.randint(0, 5) for _ in range(rnd.randint(0, 40))]
            b = [rnd.randint(0, 5) for _ in range(rnd.randint(0, 40))]
            ops = myers_opcodes(a, b)
            self.assertEqual(apply_ops(a, b, ops), b)
            for tag, i1, i2, j1, j2 in ops:
                if tag == "equal":
                    self.assertEqual(a[i1:i2], b[j1:j2])
                elif tag == "delete":
                    self.assertEqual(j1, j2)
                elif tag == "insert":
                    self.assertEqual(i1, i2)

    def test_opcodes_tile_both_sequences(self):
        rnd = random.Random(7)
        for _ in range(100):
            a = [rnd.randint(0, 3) for _ in range(rnd.randint(1, 30))]
            b = [rnd.randint(0, 3) for _ in range(rnd.randint(1, 30))]
            ops = myers_opcodes(a, b)
            i = j = 0
            for tag, i1, i2, j1, j2 in ops:
                self.assertEqual((i1, j1), (i, j))   # contiguous, no gaps/overlaps
                i, j = i2, j2
            self.assertEqual((i, j), (len(a), len(b)))

    def test_minimal_vs_difflib(self):
        rnd = random.Random(99)
        for _ in range(150):
            a = [rnd.randint(0, 4) for _ in range(rnd.randint(0, 30))]
            b = [rnd.randint(0, 4) for _ in range(rnd.randint(0, 30))]
            myers_edits = sum((i2 - i1) + (j2 - j1)
                              for tag, i1, i2, j1, j2 in myers_opcodes(a, b) if tag != "equal")
            sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
            dl_edits = sum((i2 - i1) + (j2 - j1)
                           for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
            self.assertLessEqual(myers_edits, dl_edits)   # Myers is optimal; difflib may not be

    def test_edge_cases(self):
        self.assertEqual(myers_opcodes([], []), [])
        self.assertEqual(apply_ops([1, 2, 3], [], myers_opcodes([1, 2, 3], [])), [])
        self.assertEqual(apply_ops([], [1, 2, 3], myers_opcodes([], [1, 2, 3])), [1, 2, 3])
        self.assertEqual(apply_ops([1, 2, 3], [1, 2, 3], myers_opcodes([1, 2, 3], [1, 2, 3])), [1, 2, 3])

    def test_intern_two_shares_ids(self):
        a, b = intern_two(["x", "y", "x"], ["y", "z"])
        self.assertEqual(a[0], a[2])        # both "x"
        self.assertEqual(a[1], b[0])        # "y" shared across sequences
        self.assertNotEqual(a[0], b[1])     # "x" != "z"

    def test_max_d_bail(self):
        a = list(range(0, 60))
        b = list(range(100, 160))           # fully disjoint -> edit distance 120
        with self.assertRaises(ValueError):
            myers_opcodes(a, b, max_d=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
