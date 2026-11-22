import unittest

from mho.blackbox.coarse import (
    Fingerprint, candidate_pairs, fingerprint, fingerprint_stream, rank_against, similarity,
)
from mho.blackbox.events import BlackboxEvent, EventType
from mho.blackbox.timeline import Timeline


def mk(objs, label="tl"):
    """A timeline of FILE_READ events keyed by object id (order = sequence)."""
    tl = Timeline(label=label)
    for i, o in enumerate(objs):
        tl.add(BlackboxEvent(type=EventType.FILE_READ, source="synthetic", ts=float(i),
                             operation="Read", object=f"f{o}", result="SUCCESS"))
    return tl


class SimilarityBasicsTest(unittest.TestCase):
    def test_identical_is_one(self):
        self.assertEqual(similarity(fingerprint(mk(range(50))), fingerprint(mk(range(50)))), 1.0)

    def test_disjoint_is_near_zero(self):
        s = similarity(fingerprint(mk(range(50))), fingerprint(mk(range(1000, 1050))))
        self.assertLess(s, 0.1)

    def test_prefix_shared_is_partial(self):
        a = mk(range(100))                              # 98 shingles
        b = mk(list(range(100)) + list(range(500, 550)))  # 148 shingles, 98 shared (J~0.66)
        s = similarity(fingerprint(a), fingerprint(b))
        self.assertGreater(s, 0.4)
        self.assertLess(s, 0.9)

    def test_empty_both_is_one(self):
        self.assertEqual(similarity(fingerprint(Timeline()), fingerprint(Timeline())), 1.0)

    def test_empty_vs_nonempty_is_near_zero(self):
        self.assertLess(similarity(fingerprint(Timeline()), fingerprint(mk(range(20)))), 0.05)


class DeterminismTest(unittest.TestCase):
    def test_same_input_same_sketch(self):
        self.assertEqual(list(fingerprint(mk(range(30))).sketch),
                         list(fingerprint(mk(range(30))).sketch))

    def test_roundtrip(self):
        fp = fingerprint(mk(range(20)))
        fp2 = Fingerprint.from_dict(fp.to_dict())
        self.assertEqual(list(fp.sketch), list(fp2.sketch))
        self.assertEqual((fp.num_shingles, fp.k), (fp2.num_shingles, fp2.k))

    def test_stream_matches_timeline(self):
        tl = mk(range(30), label="s")
        self.assertEqual(list(fingerprint(tl).sketch),
                         list(fingerprint_stream(iter(tl.events), label="s").sketch))

    def test_sketch_size_is_bounded(self):
        self.assertEqual(len(fingerprint(mk(range(5000))).sketch), 64)   # 512 bytes, any input


class SelectionTest(unittest.TestCase):
    def test_rank_against_orders_by_similarity(self):
        base = fingerprint(mk(range(100), label="clean"))
        cand = [
            ("clone", fingerprint(mk(range(100)))),
            ("near", fingerprint(mk(list(range(90)) + list(range(90, 150))))),
            ("distant", fingerprint(mk(range(500, 600)))),
        ]
        ranked = rank_against(base, cand)
        self.assertEqual(ranked[0][0], "clone")
        self.assertEqual(ranked[-1][0], "distant")
        self.assertEqual(ranked[0][1], 1.0)

    def test_candidate_pairs_threshold(self):
        fps = [("a", fingerprint(mk(range(100)))),
               ("b", fingerprint(mk(range(100)))),        # clone of a
               ("c", fingerprint(mk(range(500, 600))))]   # distant
        pairs = candidate_pairs(fps, threshold=0.5)
        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0][0], pairs[0][1]}, {"a", "b"})
        self.assertEqual(len(candidate_pairs(fps, threshold=0.0)), 3)

    def test_one_baseline_vs_many_dying_runs(self):
        # the blueprint's case: 1 full run + 40 that died early; only the twin survives filtering
        clean = list(range(200))
        cand = [("clean_copy", fingerprint(mk(clean)))]
        for i in range(40):
            cand.append((f"dying_{i}", fingerprint(mk(clean[:5 + i % 20]))))
        ranked = rank_against(fingerprint(mk(clean, label="clean")), cand)
        self.assertEqual(ranked[0][0], "clean_copy")
        self.assertGreater(ranked[0][1], 0.95)
        self.assertTrue(all(sim < 0.5 for name, sim in ranked if name != "clean_copy"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
