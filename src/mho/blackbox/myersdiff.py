"""Myers O(ND) diff over interned integer ids -- fast, low-memory sequence alignment.

``difflib.SequenceMatcher`` is O(n*m) in time and builds large tables; on two 50k-event
runs that is billions of cells. Myers' algorithm ("An O(ND) Difference Algorithm",
Myers 1986) runs in O((n+m)*d) where *d* is the edit distance -- and two runs of the
*same program* differ by a tiny d, so alignment is near-linear.

Two moves make it lean, exactly as the blueprint prescribes:

* **Intern, don't compare objects.** Each event's ``semantic_key()`` (a tuple) is
  mapped to a small integer id in a shared table, so the two runs become ``array('i')``
  of ids -- 4 bytes/event, and equality is an int compare. Interning is *collision-free*
  (unlike hashing), so there are no false matches.
* **Return difflib-shaped opcodes.** ``myers_opcodes`` emits ``(tag, i1, i2, j1, j2)``
  tuples with tags ``equal`` / ``delete`` / ``insert`` -- the same shape
  ``difflib.get_opcodes()`` returns -- so :class:`~mho.blackbox.diff.DiffEngine`'s
  consumer is unchanged. Only the divergent indices are ever resolved back to strings.

Pure standard library.
"""
from __future__ import annotations

from array import array


def intern_two(a_keys, b_keys) -> tuple[array, array]:
    """Map two key sequences into shared integer-id arrays (same key -> same id)."""
    table: dict = {}
    a = array("i")
    b = array("i")
    for k in a_keys:
        i = table.get(k)
        if i is None:
            i = len(table)
            table[k] = i
        a.append(i)
    for k in b_keys:
        i = table.get(k)
        if i is None:
            i = len(table)
            table[k] = i
        b.append(i)
    return a, b


def _shortest_edit_trace(a, b, max_d: int) -> list[list[int]]:
    """The per-d snapshots of Myers' furthest-reaching V array, up to the endpoint."""
    n, m = len(a), len(b)
    maxd = n + m
    offset = maxd
    v = [0] * (2 * maxd + 1)
    trace: list[list[int]] = []
    for d in range(maxd + 1):
        if d > max_d:
            raise ValueError(f"edit distance exceeds max_d={max_d}: runs too dissimilar "
                             f"to align (are they the same program? reduce first?)")
        trace.append(v.copy())
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[offset + k - 1] < v[offset + k + 1]):
                x = v[offset + k + 1]          # move down  (insert b)
            else:
                x = v[offset + k - 1] + 1       # move right (delete a)
            y = x - k
            while x < n and y < m and a[x] == b[y]:  # follow the diagonal (matches)
                x += 1
                y += 1
            v[offset + k] = x
            if x >= n and y >= m:
                return trace
    return trace


def myers_opcodes(a, b, max_d: int | None = None):
    """Minimal edit script between ``a`` and ``b`` as difflib-shaped opcodes.

    Returns a list of ``(tag, i1, i2, j1, j2)`` with tags ``equal``/``delete``/``insert``.
    Raises ``ValueError`` if the edit distance would exceed ``max_d``.
    """
    n, m = len(a), len(b)
    if max_d is None:
        max_d = n + m
    if n == 0 and m == 0:
        return []
    if n == 0:
        return [("insert", 0, 0, 0, m)]
    if m == 0:
        return [("delete", 0, n, 0, 0)]

    trace = _shortest_edit_trace(a, b, max_d)
    offset = n + m
    x, y = n, m
    steps: list[tuple] = []   # reverse-order individual moves
    for d in range(len(trace) - 1, -1, -1):
        v = trace[d]
        k = x - y
        if k == -d or (k != d and v[offset + k - 1] < v[offset + k + 1]):
            prev_k = k + 1
        else:
            prev_k = k - 1
        prev_x = v[offset + prev_k]
        prev_y = prev_x - prev_k
        while x > prev_x and y > prev_y:          # the snake (matched diagonal)
            steps.append(("equal", x - 1, y - 1))
            x -= 1
            y -= 1
        if d > 0:
            if x == prev_x:                        # came down -> inserted b[prev_y]
                steps.append(("insert", None, prev_y))
            else:                                  # came right -> deleted a[prev_x]
                steps.append(("delete", prev_x, None))
        x, y = prev_x, prev_y
    steps.reverse()

    # coalesce individual moves into contiguous opcodes
    opcodes: list[tuple] = []
    i = j = 0

    def push(tag, i2, j2):
        nonlocal i, j
        if opcodes and opcodes[-1][0] == tag:
            t, i1, _, j1, _ = opcodes[-1]
            opcodes[-1] = (t, i1, i2, j1, j2)
        else:
            opcodes.append((tag, i, i2, j, j2))
        i, j = i2, j2

    for tag, ai, bi in steps:
        if tag == "equal":
            push("equal", ai + 1, bi + 1)
        elif tag == "delete":
            push("delete", ai + 1, j)
        else:  # insert
            push("insert", i, bi + 1)
    return opcodes
