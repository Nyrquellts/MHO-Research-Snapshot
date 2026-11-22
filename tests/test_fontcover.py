"""Synthetic font tables and code-point coverage tests."""
import struct
import unicodedata
import unittest
import zlib

from mho import fontcover as F

TRUETYPE = bytes([0, 1, 0, 0])


def u(*codes):
    return "".join(chr(c) for c in codes)


# -- TrueType builders -------------------------------------------------------------------------------------------------------------

def sfnt(subtables, version=TRUETYPE, tag=b"cmap"):
    """A font with only a ``cmap`` table; ``subtables``: ``[(platform, encoding, bytes)]``."""
    records, bodies = b"", b""
    base = 4 + 8 * len(subtables)
    for platform, encoding, body in subtables:
        records += struct.pack(">HHI", platform, encoding, base + len(bodies))
        bodies += body
    table = struct.pack(">HH", 0, len(subtables)) + records + bodies
    return struct.pack(">4sHHHH", version, 1, 0, 0, 0) + struct.pack(">4sIII", tag, 0, 28, len(table)) + table


def format0(chars):
    return struct.pack(">HHH", 0, 262, 0) + bytes(1 if c in chars else 0 for c in range(256))


def format4(segments, glyph_array=()):
    """``segments``: ``[(first, last, delta, range offset)]``; the closing 0xFFFF segment is added the way a font has it."""
    segs = list(segments) + [(0xFFFF, 0xFFFF, 1, 0)]
    ends = b"".join(struct.pack(">H", s[1]) for s in segs)
    starts = b"".join(struct.pack(">H", s[0]) for s in segs)
    deltas = b"".join(struct.pack(">h", s[2]) for s in segs)
    offsets = b"".join(struct.pack(">H", s[3]) for s in segs)
    array = b"".join(struct.pack(">H", g) for g in glyph_array)
    body = struct.pack(">HHHH", 2 * len(segs), 0, 0, 0) + ends + struct.pack(">H", 0) + starts + deltas + offsets + array
    return struct.pack(">HHH", 4, 6 + len(body), 0) + body


def format6(first, glyphs):
    return struct.pack(">HHHHH", 6, 10 + 2 * len(glyphs), 0, first, len(glyphs)) + b"".join(struct.pack(">H", g) for g in glyphs)


def format_groups(fmt, groups):
    body = b"".join(struct.pack(">III", *g) for g in groups)
    return struct.pack(">HHIII", fmt, 0, 16 + len(body), 0, len(groups)) + body


ASCII = set(range(0x20, 0x7F))


class TrueTypeTest(unittest.TestCase):
    def test_format_4_delta_segment_and_glyph_array_with_a_hole(self):
        # segment 0: A..~ mapped by delta; segment 1: three characters through the glyph id array, the middle one has glyph 0 (no glyph)
        font = sfnt([(3, 1, format4([(0x20, 0x7E, 0, 0), (0xE0, 0xE2, 0, 4)], [5, 0, 7]))])
        self.assertEqual(F.ttf_codepoints(font), frozenset(ASCII | {0xE0, 0xE2}))

    def test_format_4_delta_that_wraps_to_glyph_zero_is_no_glyph(self):
        # glyph = (c + delta) mod 65536: with delta -0x41 the letter A is glyph 0 (the .notdef glyph), B is glyph 1
        font = sfnt([(3, 1, format4([(0x41, 0x43, -0x41, 0)]))])
        self.assertEqual(F.ttf_codepoints(font), frozenset({0x42, 0x43}))

    def test_format_12_groups_skip_glyph_zero(self):
        font = sfnt([(3, 10, format_groups(12, [(0x1F600, 0x1F602, 1), (0x4E00, 0x4E02, 0)]))])
        self.assertEqual(F.ttf_codepoints(font), frozenset({0x1F600, 0x1F601, 0x1F602, 0x4E01, 0x4E02}))

    def test_format_13_maps_a_range_to_one_glyph(self):
        font = sfnt([(0, 4, format_groups(13, [(0x100, 0x102, 5), (0x200, 0x202, 0)]))])
        self.assertEqual(F.ttf_codepoints(font), frozenset({0x100, 0x101, 0x102}))

    def test_format_6_and_format_0(self):
        self.assertEqual(F.ttf_codepoints(sfnt([(0, 3, format6(0x30, [1, 0, 2]))])), frozenset({0x30, 0x32}))
        self.assertEqual(F.ttf_codepoints(sfnt([(0, 3, format0({0x41, 0x42, 0xFF}))])), frozenset({0x41, 0x42, 0xFF}))

    def test_the_unicode_subtables_are_united_and_the_legacy_ones_ignored(self):
        font = sfnt([(3, 1, format4([(0x41, 0x41, 0, 0)])),
                     (0, 3, format4([(0x42, 0x42, 0, 0)])),
                     (1, 0, format4([(0x5A, 0x5A, 0, 0)])),          # Macintosh Roman
                     (3, 0, format4([(0x59, 0x59, 0, 0)]))])         # symbol
        self.assertEqual(F.ttf_codepoints(font), frozenset({0x41, 0x42}))

    def test_an_opentype_font_is_read_like_a_truetype_one(self):
        font = sfnt([(3, 1, format4([(0x41, 0x41, 0, 0)]))], version=b"OTTO")
        self.assertEqual(F.ttf_codepoints(font), frozenset({0x41}))

    def test_what_is_not_a_font_is_refused(self):
        with self.assertRaises(F.FontError):
            F.ttf_codepoints(b"this is not a font at all, just text")
        with self.assertRaises(F.FontError):
            F.ttf_codepoints(sfnt([(3, 1, format4([(0x41, 0x41, 0, 0)]))], tag=b"head"))      # no cmap table


# -- SWF builders ------------------------------------------------------------------------------------------------------------------

def define_font(name, codes, *, bold=False, italic=False, wide=True, shift_jis=False, code=F.DEFINE_FONT3):
    flags = (0x08 if wide else 0) | (0x04 if wide else 0) | (1 if bold else 0) | (2 if italic else 0) | (0x40 if shift_jis else 0)
    raw = name.encode("utf-8")
    n = len(codes)
    ow = 4 if wide else 2
    table = (n + 1) * ow + n                       # the offset table, the code table offset, one byte of "shape" per glyph
    offsets = b"".join(struct.pack("<I" if wide else "<H", (n + 1) * ow + i) for i in range(n))
    tag = struct.pack("<HBBB", 1, flags, 0, len(raw)) + raw + struct.pack("<H", n) + offsets
    tag += struct.pack("<I" if wide else "<H", table) + bytes(n)
    tag += b"".join(struct.pack("<H" if wide else "<B", c) for c in codes)
    return record(code, tag)


def record(code, body):
    if len(body) < 0x3F:
        return struct.pack("<H", (code << 6) | len(body)) + body
    return struct.pack("<HI", (code << 6) | 0x3F, len(body)) + body


def swf(*tags, signature=b"FWS"):
    body = bytes([0x08, 0x00]) + struct.pack("<HH", 0, 1) + b"".join(tags) + struct.pack("<H", 0)
    if signature in (b"CWS", b"CFX"):
        body = zlib.compress(body)
    return signature + bytes([9]) + struct.pack("<I", 8 + len(body)) + body


class SwfTest(unittest.TestCase):
    def test_a_font_with_its_name_flags_and_characters(self):
        (font,) = F.swf_fonts(swf(define_font("Test Sans", [0x41, 0x42, 0, 0x4E2D], bold=True, italic=True)))
        self.assertEqual((font.name, font.bold, font.italic, font.glyphs), ("Test Sans", True, True, 4))
        self.assertEqual(font.codes, frozenset({0x41, 0x42, 0x4E2D}))              # a code of 0 is a glyph without a character

    def test_narrow_offsets_and_codes(self):
        (font,) = F.swf_fonts(swf(define_font("Narrow", [0x41, 0x42, 0xE9], wide=False, code=F.DEFINE_FONT2)))
        self.assertEqual(font.codes, frozenset({0x41, 0x42, 0xE9}))

    def test_a_compressed_file_and_a_scaleform_file(self):
        for signature in (b"CWS", b"GFX", b"CFX"):
            (font,) = F.swf_fonts(swf(define_font("F", [0x41]), signature=signature))
            self.assertEqual(font.codes, frozenset({0x41}), signature)

    def test_several_fonts_and_other_tags_in_between(self):
        other = record(9, bytes([1, 2, 3]))                                        # SetBackgroundColor
        fonts = F.swf_fonts(swf(define_font("One", [0x41]), other, define_font("Two", list(range(0x30, 0x80)))))    # a long tag (over 62 bytes)
        self.assertEqual([f.name for f in fonts], ["One", "Two"])
        self.assertEqual(len(fonts[1].codes), 0x50)

    def test_a_shift_jis_font_is_read_through_cp932(self):
        (font,) = F.swf_fonts(swf(define_font("JP", [0x82A0, 0x41, 0x8140], shift_jis=True)))
        self.assertEqual(font.codes, frozenset({0x3042, 0x41, 0x3000}))

    def test_a_font_with_no_glyphs(self):
        (font,) = F.swf_fonts(swf(define_font("Empty", [])))
        self.assertEqual((font.glyphs, font.codes), (0, frozenset()))

    def test_a_file_that_is_not_an_swf_is_refused(self):
        for data in (b"PK" + bytes(20), b"ZWS" + bytes(20), b""):
            with self.assertRaises(F.FontError):
                F.swf_fonts(data)


# -- the languages' character sets -------------------------------------------------------------------------------------------------

class ScriptSetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sets = F.script_sets()

    def test_every_language_of_the_brief_has_a_set_without_ascii(self):
        self.assertEqual(set(self.sets), set(F.SCRIPT_LABELS))
        for label, chars in self.sets.items():
            self.assertTrue(chars, label)
            self.assertTrue(all(ord(c) > 0x7E for c in chars), label)

    def test_every_character_is_one_precomposed_code_point(self):
        for label, chars in self.sets.items():
            for c in chars:
                self.assertEqual(len(c), 1)
                self.assertTrue(unicodedata.is_normalized("NFC", c), f"{label} U+{ord(c):04X}")

    def test_the_national_standards_give_the_big_sets(self):
        hangul = [c for c in self.sets["KR"] if 0xAC00 <= ord(c) <= 0xD7A3]
        self.assertEqual(len(hangul), 2350)                                        # KS X 1001
        kanji = [c for c in self.sets["JP"] if 0x4E00 <= ord(c) <= 0x9FFF]
        self.assertEqual(len(kanji), 2965)                                         # JIS X 0208 level 1
        hanzi = [c for c in self.sets["CN"] if 0x4E00 <= ord(c) <= 0x9FFF]
        self.assertEqual(len(hanzi), 6763)                                         # GB 2312

    def test_japanese_has_the_kana_and_its_punctuation(self):
        for code in (0x3042, 0x30A2, 0x30FC, 0x300C, 0x3001, 0x3002):
            self.assertIn(chr(code), self.sets["JP"])

    def test_thai_and_arabic_have_their_letters_marks_and_digits(self):
        self.assertEqual(len(self.sets["TH"]), 58 + 15)                            # consonants and vowels U+0E01..U+0E3A, U+0E40..U+0E4E
        self.assertEqual(len(self.sets["SA"]), 26 + 10 + 8 + 10 + 3)
        self.assertIn(chr(0x0E48), self.sets["TH"])
        self.assertIn(chr(0x0661), self.sets["SA"])

    def test_vietnamese_has_every_tone_on_every_vowel(self):
        vn = self.sets["VN"]
        for code in (0x0111, 0x0110, 0x1EA1, 0x1EAD, 0x01B0, 0x1EEB, 0x1EF9, 0x01A1):
            self.assertIn(chr(code), vn, hex(code))
        self.assertGreater(len(vn), 130)

    def test_the_european_languages_have_their_accents(self):
        self.assertTrue(set(u(0xE9, 0xE8, 0xE7, 0xE0, 0x153)) <= self.sets["FR"])
        self.assertTrue(set(u(0xE4, 0xF6, 0xFC, 0xDF)) <= self.sets["DE"])
        self.assertTrue(set(u(0xF1, 0xBF, 0xA1, 0xE1)) <= self.sets["ES"])
        self.assertTrue(set(u(0xE3, 0xF5, 0xE7)) <= self.sets["PT"])
        self.assertTrue(set(u(0xE0, 0xE8, 0xEC, 0xF2, 0xF9)) <= self.sets["IT"])
        self.assertIn(chr(0xF1), self.sets["PH"])

    def test_the_capital_sharp_s_is_optional_because_ss_capitalises(self):
        self.assertNotIn(chr(0x1E9E), self.sets["DE"])

    def test_the_guillemets_and_the_low_quote_are_only_asked_of_the_languages_that_write_them(self):
        for label in ("FR", "ES", "IT"):
            self.assertTrue(F.GUILLEMETS <= self.sets[label], label)
        for label in ("EN", "ID", "DE", "VN"):
            self.assertFalse(F.GUILLEMETS & self.sets[label], label)
        self.assertTrue(F.LOW_QUOTE <= self.sets["DE"])
        self.assertFalse(F.LOW_QUOTE & self.sets["EN"])

    def test_english_needs_only_typographic_punctuation(self):
        self.assertEqual(self.sets["EN"], frozenset(F.TYPOGRAPHY))

    def test_arabic_presentation_forms_are_the_joined_letter_shapes(self):
        forms = F.arabic_presentation_forms()
        self.assertIn(chr(0xFE8D), forms)                                          # alef, isolated
        self.assertIn(chr(0xFEDF), forms)                                          # lam, initial
        self.assertNotIn(chr(0xFE75), forms)                                       # unassigned
        self.assertFalse(forms & self.sets["SA"])


class CoverageTest(unittest.TestCase):
    def test_what_a_font_lacks_is_named_and_sorted(self):
        cov = F.coverage({0x41, 0x43}, "CBA", "X")
        self.assertEqual((cov.label, cov.need, cov.have, cov.missing), ("X", 3, 2, ("B",)))
        self.assertFalse(cov.complete)
        self.assertAlmostEqual(cov.ratio, 2 / 3)

    def test_a_complete_font_and_an_empty_need(self):
        self.assertTrue(F.coverage({0x41}, "A").complete)
        self.assertEqual(F.coverage(set(), "").ratio, 1.0)

    def test_a_report_covers_every_font_against_every_language(self):
        punctuation = {ord(c) for c in F.TYPOGRAPHY | F.GUILLEMETS | F.LOW_QUOTE}
        report = F.font_report({"latin": frozenset(range(0x20, 0x250)) | punctuation, "none": frozenset()})
        self.assertTrue(report["latin"]["FR"].complete)
        self.assertTrue(report["latin"]["DE"].complete)
        self.assertFalse(report["latin"]["KR"].complete)
        self.assertEqual(report["none"]["EN"].have, 0)
        self.assertEqual(set(report["latin"]), set(F.SCRIPT_LABELS))


# -- the snapshot ------------------------------------------------------------------------------------------------------------------

class RangesTest(unittest.TestCase):
    def test_runs_are_merged_and_sorted(self):
        self.assertEqual(F.ranges_of([5, 3, 4, 9, 3, 1]), [(1, 1), (3, 5), (9, 9)])
        self.assertEqual(F.ranges_of([]), [])

    def test_the_text_form_round_trips(self):
        codes = frozenset(list(range(0x20, 0x7F)) + [0xE9, 0x4E00, 0x4E01, 0x1F600])
        text = F.encode_ranges(codes)
        self.assertEqual(text, "20-7E,E9,4E00-4E01,1F600")
        self.assertEqual(F.decode_ranges(text), codes)
        self.assertEqual(F.decode_ranges(""), frozenset())
        self.assertEqual(F.decode_ranges(" 41 , 43-44 "), frozenset({0x41, 0x43, 0x44}))
        self.assertEqual(F.codes_of([(1, 3), (7, 7)]), frozenset({1, 2, 3, 7}))


if __name__ == "__main__":
    unittest.main()
