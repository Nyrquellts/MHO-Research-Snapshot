"""Coarse pairwise pre-filter (MinHash over event-key shingles).

"Hierarchical compare, not one giant alignment." Given N runs -- say 40 launches that
died early plus 1 that connected -- deciding *which pair is worth Myers-diffing* should
cost O(N) tiny sketch comparisons, not N full alignments. This module fingerprints each
run into a small MinHash sketch of the k-shingles of its interned semantic keys, then
estimates Jaccard similarity between two fingerprints in O(sketch_size). Only pairs above
a threshold need :class:`~mho.blackbox.diff.DiffEngine` (Myers).

* fingerprint a Timeline (or an event iterator) -> :class:`Fingerprint`;
* :func:`similarity` -- estimated Jaccard in [0, 1];
* :func:`rank_against` -- 1:N, sort candidates by similarity to a baseline;
* :func:`candidate_pairs` -- N:N, keep only the close pairs.

Deterministic (same input -> same sketch, across processes). Sketches are tiny
(64 x 8 bytes = 512 bytes) regardless of run length, so a whole campaign fingerprints
into a few kilobytes. Pure standard library.
"""
from __future__ import annotations

import hashlib
import random
from array import array
from dataclasses import dataclass

# 61-bit Mersenne prime: MinHash coefficients form a linear hash family
#   h(x) = (a * x + b) mod P,   a in [1, P), b in [0, P).
_P = (1 << 61) - 1
_MAX = _P                       # sentinel strictly greater than any real hash value
_MASK = 0xFFFFFFFFFFFFFFFF
_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_DEFAULT_SEED = 0x0B1ACC80BC0A125E
_COEFFS_CACHE: dict = {}


def _get_coefficients(num_hashes: int, seed: int = _DEFAULT_SEED):
    """Deterministic (a, b) coefficient pairs; cached per (num_hashes, seed)."""
    key = (num_hashes, seed)
    cached = _COEFFS_CACHE.get(key)
    if cached is None:
        r = random.Random(seed)
        cached = [(r.randrange(1, _P), r.randrange(0, _P)) for _ in range(num_hashes)]
        _COEFFS_CACHE[key] = cached
    return cached


def _hash64(key) -> int:
    """Stable 64-bit hash of a semantic key (a tuple), the same across processes."""
    return int.from_bytes(hashlib.blake2b(repr(key).encode("utf-8"), digest_size=8).digest(),
                          "little")


def _combine(chunk) -> int:
    """FNV-1a rolling combine of a small tuple of 64-bit hashes -> one 64-bit shingle."""
    h = _FNV_OFFSET
    for x in chunk:
        h = ((h ^ x) * _FNV_PRIME) & _MASK
    return h


def _shingles(key_hashes: list, k: int) -> list:
    """All k-shingles as combined 64-bit hashes. A run shorter than k yields the whole
    sequence as a single shingle (so tiny runs still fingerprint distinctly)."""
    n = len(key_hashes)
    if n < k:
        return [_combine(key_hashes)] if key_hashes else []
    return [_combine(key_hashes[i:i + k]) for i in range(n - k + 1)]


@dataclass
class Fingerprint:
    sketch: array
    num_shingles: int
    label: str = ""
    k: int = 3

    def to_dict(self) -> dict:
        return {"schema": "nyr.blackbox.coarse/1", "label": self.label, "k": self.k,
                "num_shingles": self.num_shingles, "sketch": list(self.sketch)}

    @classmethod
    def from_dict(cls, d: dict) -> "Fingerprint":
        return cls(sketch=array("Q", d["sketch"]), num_shingles=int(d.get("num_shingles", 0)),
                   label=d.get("label", ""), k=int(d.get("k", 3)))


def _fingerprint_from_key_hashes(key_hashes: list, k: int, num_hashes: int,
                                 label: str = "") -> Fingerprint:
    shingles = _shingles(key_hashes, k)
    if not shingles:
        return Fingerprint(array("Q", [_MAX] * num_hashes), 0, label, k)
    coeffs = _get_coefficients(num_hashes)
    # For each hash function, the min over all shingles is one sketch slot.
    sketch = array("Q", (min(((a * s + b) % _P) for s in shingles) for (a, b) in coeffs))
    return Fingerprint(sketch, len(shingles), label, k)


def fingerprint(timeline, k: int = 3, num_hashes: int = 64) -> Fingerprint:
    """Fingerprint a Timeline from each event's ``semantic_key()``."""
    key_hashes = [_hash64(ev.semantic_key()) for ev in timeline.events]
    return _fingerprint_from_key_hashes(key_hashes, k, num_hashes,
                                        getattr(timeline, "label", ""))


def fingerprint_stream(events, k: int = 3, num_hashes: int = 64, label: str = "") -> Fingerprint:
    """Fingerprint an event iterator (for a coarse pass before/without reduction).
    Bounded output -- the sketch is ~512 bytes regardless of event count."""
    key_hashes = [_hash64(ev.semantic_key()) for ev in events]
    return _fingerprint_from_key_hashes(key_hashes, k, num_hashes, label)


def similarity(a: Fingerprint, b: Fingerprint) -> float:
    """Estimated Jaccard similarity of the two shingle sets, in [0, 1]. Two empty
    fingerprints compare as identical (1.0)."""
    if len(a.sketch) != len(b.sketch):
        raise ValueError("fingerprints must share num_hashes to compare")
    if not a.sketch:
        return 1.0
    matches = sum(1 for x, y in zip(a.sketch, b.sketch) if x == y)
    return matches / len(a.sketch)


def rank_against(baseline: Fingerprint, candidates):
    """1:N -- sort labelled candidates by similarity to ``baseline``, highest first.
    ``candidates`` is an iterable of ``(name, Fingerprint)``."""
    scored = [(name, similarity(baseline, fp)) for name, fp in candidates]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def candidate_pairs(fingerprints, threshold: float = 0.5):
    """N:N -- from labelled fingerprints, return only ``(a, b, similarity)`` above
    ``threshold`` (the pairs worth full Myers-diffing), sorted highest first."""
    fps = list(fingerprints)
    pairs = []
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            s = similarity(fps[i][1], fps[j][1])
            if s >= threshold:
                pairs.append((fps[i][0], fps[j][0], s))
    pairs.sort(key=lambda t: t[2], reverse=True)
    return pairs
