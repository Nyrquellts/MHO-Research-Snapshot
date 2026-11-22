"""Offline glyph coverage checks for TrueType, OpenType, and SWF font tables.

The parsers read character maps from bytes, and the coverage report compares
those maps against character sets built from standard encodings. The result
measures available glyphs. Shaping and visual layout need rendering tests.
"""
from __future__ import annotations

import struct
import unicodedata
import zlib
from dataclasses import dataclass
from typing import Iterable


class FontError(ValueError):
    """The bytes are not a font this module reads."""


# -- TrueType / OpenType ---------------------------------------------------------------------------------------------------------

def _u16(b: bytes, at: int) -> int:
    return struct.unpack_from(">H", b, at)[0]


def _u32(b: bytes, at: int) -> int:
    return struct.unpack_from(">I", b, at)[0]


def _i16(b: bytes, at: int) -> int:
    return struct.unpack_from(">h", b, at)[0]


def _tables(data: bytes) -> dict[bytes, tuple[int, int]]:
    base = _u32(data, 12) if data[:4] == b"ttcf" else 0       # the first font of a collection
    if data[base:base + 4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
        raise FontError("not a TrueType / OpenType font")
    out: dict[bytes, tuple[int, int]] = {}
    for i in range(_u16(data, base + 4)):
        tag, _checksum, offset, length = struct.unpack_from(">4sIII", data, base + 12 + 16 * i)
        out[tag] = (offset, length)
    return out


def _subtable(data: bytes, at: int) -> set[int]:
    """The characters one ``cmap`` subtable maps to a real glyph (glyph 0 is .notdef, not a glyph)."""
    fmt = _u16(data, at)
    chars: set[int] = set()
    if fmt == 0:
        chars.update(c for c in range(256) if data[at + 6 + c])
    elif fmt == 4:
        span = _u16(data, at + 6)
        ends = at + 14
        starts = ends + span + 2
        deltas = starts + span
        ranges = deltas + span
        for s in range(span // 2):
            end, start = _u16(data, ends + 2 * s), _u16(data, starts + 2 * s)
            delta, offset = _i16(data, deltas + 2 * s), _u16(data, ranges + 2 * s)
            for c in range(start, end + 1):
                if offset == 0:
                    glyph = (c + delta) & 0xFFFF
                else:
                    where = ranges + 2 * s + offset + 2 * (c - start)
                    if where + 2 > len(data):
                        continue
                    glyph = _u16(data, where)
                    if glyph:
                        glyph = (glyph + delta) & 0xFFFF
                if glyph:
                    chars.add(c)
    elif fmt == 6:
        first, count = _u16(data, at + 6), _u16(data, at + 8)
        chars.update(first + i for i in range(count) if _u16(data, at + 10 + 2 * i))
    elif fmt in (12, 13):
        for i in range(_u32(data, at + 12)):
            start, end, glyph = struct.unpack_from(">III", data, at + 16 + 12 * i)
            if fmt == 12:
                chars.update(c for c in range(start, end + 1) if glyph + (c - start))
            elif glyph:
                chars.update(range(start, end + 1))
    return chars                                        # formats 2, 8, 10 and 14 are not used by the client's fonts


def ttf_codepoints(data: bytes) -> frozenset[int]:
    """Every Unicode code point the font has a glyph for (the union of its Unicode ``cmap`` subtables)."""
    tables = _tables(data)
    if b"cmap" not in tables:
        raise FontError("the font has no cmap table")
    cmap = tables[b"cmap"][0]
    chars: set[int] = set()
    for i in range(_u16(data, cmap + 2)):
        platform, encoding, offset = struct.unpack_from(">HHI", data, cmap + 4 + 8 * i)
        if platform == 0 or (platform == 3 and encoding in (1, 10)):     # Unicode subtables, not the legacy code pages or symbol
            chars |= _subtable(data, cmap + offset)
    return frozenset(chars)


# -- SWF / Scaleform GFX -----------------------------------------------------------------------------------------------------------

DEFINE_FONT2, DEFINE_FONT3 = 48, 75


@dataclass(frozen=True)
class SwfFont:
    name: str
    bold: bool
    italic: bool
    glyphs: int
    codes: frozenset[int]


def _swf_code(code: int, shift_jis: bool) -> str | None:
    if not shift_jis:
        return chr(code)
    try:
        return (bytes((code >> 8, code & 0xFF)) if code > 0xFF else bytes((code,))).decode("cp932")
    except UnicodeDecodeError:
        return None


def _define_font(tag: bytes) -> SwfFont:
    """DefineFont2 / DefineFont3: id, flags, language, name, glyph count, offset table, code-table offset, shapes, code table."""
    flags = tag[2]
    wide_offsets, wide_codes = bool(flags & 0x08), bool(flags & 0x04)
    name_end = 5 + tag[4]
    name = tag[5:name_end].decode("utf-8", "replace").rstrip("\0")
    glyphs = struct.unpack_from("<H", tag, name_end)[0]
    if glyphs == 0:
        return SwfFont(name, bool(flags & 1), bool(flags & 2), 0, frozenset())
    table = name_end + 2                                            # the offsets are counted from the start of the offset table
    after = table + (4 if wide_offsets else 2) * glyphs
    code_offset = struct.unpack_from("<I" if wide_offsets else "<H", tag, after)[0]
    codes = struct.unpack_from(f"<{glyphs}{'H' if wide_codes else 'B'}", tag, table + code_offset)
    shift_jis = bool(flags & 0x40)
    chars = frozenset(ord(ch) for ch in (_swf_code(c, shift_jis) for c in codes if c) if ch)
    return SwfFont(name, bool(flags & 1), bool(flags & 2), glyphs, chars)


def swf_fonts(data: bytes) -> list[SwfFont]:
    """The embedded fonts of an SWF (``FWS`` / ``CWS``) or Scaleform GFX (``GFX`` / ``CFX``) file."""
    signature = data[:3]
    if signature in (b"FWS", b"GFX"):
        body = data[8:]
    elif signature in (b"CWS", b"CFX"):
        body = zlib.decompress(data[8:])
    else:
        raise FontError(f"not an SWF / GFX file (signature {signature!r})")      # ZWS (LZMA) is not what the client ships
    pos = (5 + 4 * (body[0] >> 3) + 7) // 8 + 4                     # the stage RECT, then the frame rate and the frame count
    fonts: list[SwfFont] = []
    while pos + 2 <= len(body):
        head = struct.unpack_from("<H", body, pos)[0]
        pos += 2
        tag, length = head >> 6, head & 0x3F
        if length == 0x3F:
            length = struct.unpack_from("<I", body, pos)[0]
            pos += 4
        if tag == 0:
            break
        if tag in (DEFINE_FONT2, DEFINE_FONT3):
            fonts.append(_define_font(body[pos:pos + length]))
        pos += length
    return fonts


# -- what each target language needs -----------------------------------------------------------------------------------------------

def _from_codec(codec: str, leads: Iterable[int], trails: Iterable[int]) -> set[str]:
    trails = list(trails)
    out: set[str] = set()
    for lead in leads:
        for trail in trails:
            try:
                ch = bytes((lead, trail)).decode(codec)
            except UnicodeDecodeError:
                continue
            if len(ch) == 1:
                out.add(ch)
    return out


def _span(first: int, last: int) -> set[str]:
    return {chr(c) for c in range(first, last + 1)}


def _vietnamese() -> set[str]:
    """Every Vietnamese vowel with its tone mark, composed the way the language is written (NFC), and the crossed d."""
    marks = tuple(chr(c) for c in (0x0300, 0x0301, 0x0309, 0x0303, 0x0323))     # grave, acute, hook above, tilde, dot below
    out = {chr(0x0111), chr(0x0110)}                                              # d with stroke, both cases
    for base in "aăâeêioôơuưy" + "AĂÂEÊIOÔƠUƯY":
        out.add(base)
        for mark in marks:
            composed = unicodedata.normalize("NFC", base + mark)
            if len(composed) == 1:
                out.add(composed)
    return out


ASCII_PRINTABLE = _span(0x20, 0x7E)
# what a translation uses beyond ASCII punctuation: the curly quotes, the ellipsis and the dashes (every language) ...
TYPOGRAPHY = set(chr(c) for c in (0x2019, 0x2018, 0x201C, 0x201D, 0x2026, 0x2013, 0x2014))
GUILLEMETS = {chr(0x00AB), chr(0x00BB)}                  # ... the guillemets (French, Spanish, Italian) ...
LOW_QUOTE = {chr(0x201E)}                                # ... and the German low double quote

# The owner's labels for the target set (the Guild Halls'): the keys of every per-locale table in the toolkit.
SCRIPT_LABELS = ("EN", "ID", "JP", "KR", "PH", "CN", "FR", "VN", "PT", "TH", "DE", "SA", "IT", "ES")


def script_sets() -> dict[str, frozenset[str]]:
    """Per locale label: the characters its orthography needs beyond ASCII. Built once per call from the standards' code pages."""
    hangul = _from_codec("euc_kr", range(0xB0, 0xC9), range(0xA1, 0xFF))                 # KS X 1001 hangul rows
    kanji1 = {c for c in _from_codec("shift_jis", range(0x88, 0x99), range(0x40, 0xFD))
              if 0x4E00 <= ord(c) <= 0x9FFF}                                              # JIS X 0208 level 1 (rows 16-47)
    kanji1 -= {c for c in _from_codec("shift_jis", [0x98], range(0x73, 0xFD)) if 0x4E00 <= ord(c) <= 0x9FFF}     # from 0x9873 the level 2 kanji begin
    hanzi = {c for c in _from_codec("gb2312", range(0xB0, 0xF8), range(0xA1, 0xFF)) if 0x4E00 <= ord(c) <= 0x9FFF}
    kana = _span(0x3041, 0x3096) | _span(0x30A1, 0x30FA) | set(chr(c) for c in (0x30FC, 0x30FB, 0x300C, 0x300D, 0x3001, 0x3002))
    sets = {
        "EN": set(TYPOGRAPHY),
        "ID": set(TYPOGRAPHY),
        "PH": set("ñÑ") | TYPOGRAPHY,
        "FR": set("àâæçéèêëîïôœùûüÿÀÂÆÇÉÈÊËÎÏÔŒÙÛÜŸ") | TYPOGRAPHY | GUILLEMETS,
        "DE": set("äöüßÄÖÜ") | TYPOGRAPHY | LOW_QUOTE,            # the capital sharp s (U+1E9E) is optional: ss capitalises to SS
        "ES": set("áéíóúüñÁÉÍÓÚÜÑ¿¡") | TYPOGRAPHY | GUILLEMETS,
        "PT": set("ãõáâàçéêíóôúüÃÕÁÂÀÇÉÊÍÓÔÚÜ") | TYPOGRAPHY,
        "IT": set("àèéìíîòóùúÀÈÉÌÍÎÒÓÙÚ") | TYPOGRAPHY | GUILLEMETS,
        "VN": _vietnamese() | TYPOGRAPHY,
        "TH": _span(0x0E01, 0x0E3A) | _span(0x0E40, 0x0E4E),
        "SA": _span(0x0621, 0x063A) | _span(0x0641, 0x064A) | _span(0x064B, 0x0652) | _span(0x0660, 0x0669) | set(chr(c) for c in (0x060C, 0x061B, 0x061F)),
        "KR": hangul | TYPOGRAPHY,
        "JP": kana | kanji1,
        "CN": hanzi,
    }
    return {label: frozenset(sets[label] - ASCII_PRINTABLE) for label in SCRIPT_LABELS}


def arabic_presentation_forms() -> frozenset[str]:
    """Arabic Presentation Forms-B (isolated / initial / medial / final letter shapes): what an engine without a joining shaper draws."""
    return frozenset(_span(0xFE70, 0xFEFC) - {chr(0xFE75)})


# -- coverage -------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Coverage:
    label: str
    need: int
    have: int
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.have == self.need

    @property
    def ratio(self) -> float:
        return self.have / self.need if self.need else 1.0


def coverage(codes: frozenset[int] | set[int], need: Iterable[str], label: str = "") -> Coverage:
    """How much of ``need`` the code points ``codes`` cover, and which characters they lack (sorted)."""
    need = sorted(set(need))
    missing = tuple(c for c in need if ord(c) not in codes)
    return Coverage(label, len(need), len(need) - len(missing), missing)


def font_report(fonts: dict[str, frozenset[int]]) -> dict[str, dict[str, Coverage]]:
    """``{font name: {locale label: Coverage}}`` for every font against every target language."""
    sets = script_sets()
    return {name: {label: coverage(codes, sets[label], label) for label in SCRIPT_LABELS} for name, codes in fonts.items()}


def ranges_of(codes: Iterable[int]) -> list[tuple[int, int]]:
    """The sorted, merged ``(first, last)`` runs of a set of code points."""
    out: list[tuple[int, int]] = []
    for c in sorted(set(codes)):
        if out and c == out[-1][1] + 1:
            out[-1] = (out[-1][0], c)
        else:
            out.append((c, c))
    return out


def codes_of(ranges: Iterable[tuple[int, int]]) -> frozenset[int]:
    return frozenset(c for first, last in ranges for c in range(first, last + 1))


def encode_ranges(codes: Iterable[int]) -> str:
    """``"20-7E,A0-FF,4E00"``: hexadecimal runs (a single code point is written alone)."""
    return ",".join(f"{a:X}" if a == b else f"{a:X}-{b:X}" for a, b in ranges_of(codes))


def decode_ranges(text: str) -> frozenset[int]:
    codes: set[int] = set()
    for part in filter(None, (p.strip() for p in text.split(","))):
        first, _, last = part.partition("-")
        codes.update(range(int(first, 16), int(last or first, 16) + 1))
    return frozenset(codes)
