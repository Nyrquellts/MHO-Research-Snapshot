"""Stage 2 -- terrain heightfield -> ground elevation lookup.

A ``MapGrid`` is a regular 2D grid of elevation samples covering the axis-aligned
world rectangle [min_x, max_x] x [min_y, max_y]. ``get_ground_z(x, y)`` returns the
interpolated ground height at a world position, which the server tick uses to clamp
every monster (and NPC) onto the terrain plane each frame:

    monster.z = grid.get_ground_z(monster.x, monster.y)

Invariants that make this safe to call inside a fixed-rate tick loop:

* Construction validates that every elevation sample is finite -- a grid can never
  hold NaN/inf, so a lookup can never *return* NaN/inf for a finite query.
* Queries outside the rectangle clamp to the nearest edge rather than extrapolating.
* A non-finite query coordinate raises ``ValueError`` (a caller bug worth surfacing
  loudly) instead of silently poisoning downstream physics.

Bilinear interpolation, using only the Python standard library.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass


def _finite(v: float, what: str) -> float:
    f = float(v)
    if not math.isfinite(f):
        raise ValueError(f"{what} must be finite, got {v!r}")
    return f


@dataclass
class MapGrid:
    """A regular elevation grid over an axis-aligned world rectangle.

    ``elevation`` is row-major: ``elevation[row][col]`` where ``row`` runs along Y
    (from min_y at row 0 to max_y at row rows-1) and ``col`` runs along X. ``rows`` and
    ``cols`` are each >= 2 so a cell has real extent in both axes.
    """

    min_x: float
    max_x: float
    min_y: float
    max_y: float
    elevation: list[list[float]]

    def __post_init__(self) -> None:
        self.min_x = _finite(self.min_x, "min_x")
        self.max_x = _finite(self.max_x, "max_x")
        self.min_y = _finite(self.min_y, "min_y")
        self.max_y = _finite(self.max_y, "max_y")
        if self.max_x <= self.min_x or self.max_y <= self.min_y:
            raise ValueError("max bounds must exceed min bounds")
        rows = len(self.elevation)
        if rows < 2:
            raise ValueError("grid needs >= 2 rows")
        cols = len(self.elevation[0])
        if cols < 2:
            raise ValueError("grid needs >= 2 cols")
        for r, row in enumerate(self.elevation):
            if len(row) != cols:
                raise ValueError(f"row {r} has {len(row)} cols, expected {cols}")
            self.elevation[r] = [_finite(v, f"elevation[{r}][{c}]") for c, v in enumerate(row)]
        self._rows = rows
        self._cols = cols

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def cols(self) -> int:
        return self._cols

    def get_ground_z(self, world_x: float, world_y: float) -> float:
        """Interpolated ground height at (world_x, world_y). Always finite.

        Out-of-bounds queries clamp to the nearest edge. Sub-microsecond in intent:
        four array reads and a handful of multiplies, no allocation.
        """
        x = _finite(world_x, "world_x")
        y = _finite(world_y, "world_y")

        # Normalise to fractional grid coordinates, clamped to the valid cell range.
        gx = (x - self.min_x) / (self.max_x - self.min_x) * (self._cols - 1)
        gy = (y - self.min_y) / (self.max_y - self.min_y) * (self._rows - 1)
        gx = 0.0 if gx < 0.0 else (self._cols - 1 if gx > self._cols - 1 else gx)
        gy = 0.0 if gy < 0.0 else (self._rows - 1 if gy > self._rows - 1 else gy)

        c0 = int(gx)
        r0 = int(gy)
        c1 = c0 + 1 if c0 < self._cols - 1 else c0
        r1 = r0 + 1 if r0 < self._rows - 1 else r0
        fx = gx - c0
        fy = gy - r0

        e = self.elevation
        top = e[r0][c0] * (1.0 - fx) + e[r0][c1] * fx
        bot = e[r1][c0] * (1.0 - fx) + e[r1][c1] * fx
        return top * (1.0 - fy) + bot * fy

    def contains(self, world_x: float, world_y: float) -> bool:
        return self.min_x <= world_x <= self.max_x and self.min_y <= world_y <= self.max_y

    # -- constructors -----------------------------------------------------------

    @classmethod
    def from_flat(
        cls,
        min_x: float,
        max_x: float,
        min_y: float,
        max_y: float,
        cols: int,
        rows: int,
        values,
    ) -> "MapGrid":
        """Build from a flat row-major sequence of ``rows*cols`` elevations."""
        values = list(values)
        if len(values) != rows * cols:
            raise ValueError(f"expected {rows * cols} values, got {len(values)}")
        grid = [values[r * cols:(r + 1) * cols] for r in range(rows)]
        return cls(min_x, max_x, min_y, max_y, grid)

    @classmethod
    def flat_plane(cls, min_x, max_x, min_y, max_y, z=0.0, cols=2, rows=2) -> "MapGrid":
        """A perfectly flat grid at height ``z`` -- the simplest test fixture."""
        return cls.from_flat(min_x, max_x, min_y, max_y, cols, rows, [float(z)] * (cols * rows))

    @classmethod
    def from_heightmap(cls, rows_u16, height_ratio: float = 1.0, unit_scale: float = 1.0,
                       origin=(0.0, 0.0)) -> "MapGrid":
        """Build a grid from a CryEngine-style ``uint16`` heightmap.

        ``rows_u16`` is a 2D sequence ``[row][col]`` of raw uint16 samples (row index runs
        along +Y, col along +X, as CryEngine stores sectors). World height per sample is
        ``raw * height_ratio``; samples are ``unit_scale`` world units apart, with the
        sample at ``[0][0]`` placed at ``origin``. This is the tested ingest path for a
        parsed ``terrain.dat`` (see mho.loaders.parse_cryengine_terrain)."""
        rows_u16 = [list(r) for r in rows_u16]
        nrows = len(rows_u16)
        ncols = len(rows_u16[0]) if nrows else 0
        elevation = [[raw * height_ratio for raw in row] for row in rows_u16]
        ox, oy = origin
        return cls(ox, ox + (ncols - 1) * unit_scale, oy, oy + (nrows - 1) * unit_scale, elevation)

    # -- serialization ----------------------------------------------------------
    #
    # A compact self-describing binary so a parsed CryEngine heightfield can be
    # cached to disk and reloaded without re-reading the .ifs. Little-endian:
    #   magic 'MGRD' | u32 version=1 | u32 cols | u32 rows | 4x f64 bounds | rows*cols f32
    MAGIC = b"MGRD"

    def to_bytes(self) -> bytes:
        out = bytearray()
        out += self.MAGIC
        out += struct.pack("<III", 1, self._cols, self._rows)
        out += struct.pack("<dddd", self.min_x, self.max_x, self.min_y, self.max_y)
        for row in self.elevation:
            out += struct.pack(f"<{self._cols}f", *row)
        return bytes(out)

    @classmethod
    def from_bytes(cls, data: bytes) -> "MapGrid":
        if data[:4] != cls.MAGIC:
            raise ValueError("bad magic; not a MapGrid blob")
        version, cols, rows = struct.unpack_from("<III", data, 4)
        if version != 1:
            raise ValueError(f"unsupported MapGrid version {version}")
        min_x, max_x, min_y, max_y = struct.unpack_from("<dddd", data, 16)
        off = 48
        values = []
        for _ in range(rows):
            values.extend(struct.unpack_from(f"<{cols}f", data, off))
            off += cols * 4
        return cls.from_flat(min_x, max_x, min_y, max_y, cols, rows, values)
