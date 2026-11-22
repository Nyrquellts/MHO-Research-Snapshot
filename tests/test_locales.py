"""Locale, catalog, and text checks using synthetic fixtures."""
import copy
import dataclasses
import unittest

from mho import locales as L

def example_locale(tag, label, script="Latn", *, aliases=(), group=",", decimal=".", identical_ok=()):
    return L.Locale(
        tag=tag, label=label, english=tag, native=tag, script=script,
        rtl=script == "Arab", aliases=aliases,
        plural_required=L.plural_forms(tag), plural_all=L.plural_forms(tag, required=False),
        group=group, decimal=decimal, min_group=1, review="canonical" if tag == "en" else "draft",
        variant_decided=tag != "pt-BR", variant_note="", identical_ok=identical_ok,
    )


REG = L.Registry("en", (
    example_locale("en", "EN"),
    example_locale("id", "ID", group=".", decimal=",", identical_ok=("example.item",)),
    example_locale("ja", "JP", "Jpan", aliases=("jp",)),
    example_locale("ko", "KR", "Kore", aliases=("kr",)),
    example_locale("fil", "PH", aliases=("tl",)),
    example_locale("zh-Hans", "CN", "Hans", aliases=("zh-CN",)),
    example_locale("fr", "FR", group=" ", decimal=","),
    example_locale("vi", "VN"),
    example_locale("pt-BR", "PT", aliases=("pt",)),
    example_locale("th", "TH", "Thai"),
    example_locale("de", "DE", group=".", decimal=","),
    example_locale("ar", "SA", "Arab"),
    example_locale("it", "IT"),
    example_locale("es", "ES"),
), fragments=("example.quantity",))


def example_catalog(tag):
    plain, quantity, status = {
        "en": ("Stage {level} started", "Quantity {count}", "New batch ready"),
        "de": ("Stufe {level} begonnen", "Anzahl {count}", "Neue Charge bereit"),
        "ar": ("بدأت المرحلة {level}", "الكمية {count}", "الدفعة الجديدة جاهزة"),
        "ja": ("段階 {level} を開始", "個数 {count}", "新しい処理が可能"),
    }[tag]
    return L.parse_catalog(tag, {
        "example.quantity": {form: quantity for form in L.plural_forms(tag)},
        "example.stage": plain,
        "example.ready": status,
    })

NBSP = chr(0xA0)


def u(*codes):
    return "".join(chr(c) for c in codes)


def loc(tag):
    found = REG.get(tag)
    assert found is not None, tag
    return found


def codes(tag, text, english=None, key="town.example", **kw):
    """The ``(level, code)`` pairs the checks report for a text."""
    return {(f.level, f.code) for f in L.text_findings(loc(tag), key, text, english, **kw)}


def error_codes(tag, text, english=None, **kw):
    return {code for level, code in codes(tag, text, english, **kw) if level == "error"}


class RegistryTest(unittest.TestCase):
    def test_the_registry_is_sound(self):
        self.assertEqual(L.registry_problems(REG), [])

    def test_the_briefs_fourteen_languages_in_the_briefs_order(self):
        self.assertEqual([x.label for x in REG.locales], list(L.BRIEF_LABELS))
        self.assertEqual(len({x.tag for x in REG.locales}), 14)

    def test_english_is_the_only_canonical_language(self):
        self.assertEqual([x.tag for x in REG.locales if x.review == "canonical"], [REG.default])
        self.assertEqual(REG.default, "en")

    def test_a_requested_tag_resolves_the_way_the_server_does(self):
        for asked, tag in (("en_US", "en"), ("EN-gb", "en"), ("tl", "fil"), ("jp", "ja"), ("kr", "ko"), ("zh-CN", "zh-Hans"), ("pt", "pt-BR"),
                           ("id-ID", "id"), ("ar-SA", "ar")):
            self.assertEqual(REG.resolve(asked), tag, asked)
        self.assertIsNone(REG.resolve("xx"))
        self.assertIsNone(REG.resolve(""))
        self.assertIsNone(REG.resolve("   "))

    def test_a_broken_registry_is_found(self):
        def problems(**changes):
            broken = tuple(dataclasses.replace(x, **changes) if x.tag == "de" else x for x in REG.locales)
            return L.registry_problems(dataclasses.replace(REG, locales=broken))

        self.assertTrue(any("plural_required" in p for p in problems(plural_required=("other",))))
        self.assertTrue(any("plural_all" in p for p in problems(plural_all=("one", "many", "other"))))
        self.assertTrue(any("review" in p for p in problems(review="perfect")))
        self.assertTrue(any("canonical" in p for p in problems(review="canonical")))
        self.assertTrue(any("min_group" in p for p in problems(min_group=0)))
        self.assertTrue(any("names both" in p for p in problems(aliases=("fr",))))
        self.assertTrue(any("not listed" in p for p in L.registry_problems(dataclasses.replace(REG, default="xx"))))
        self.assertTrue(any("labels" in p for p in L.registry_problems(dataclasses.replace(REG, locales=REG.locales[:-1]))))


class PluralTest(unittest.TestCase):
    def test_the_contract_must_cover_every_language(self):
        self.assertTrue(any("no plural vectors" in p for p in L.vector_problems({"en": {"one": [1], "other": [2]}}, REG)))

    def test_a_disagreement_is_reported(self):
        self.assertTrue(any("en: 2 is 'other'" in p for p in L.vector_problems({"en": {"one": [2]}}, dataclasses.replace(REG, locales=(loc("en"),)))))

    def test_known_counts(self):
        for tag, count, form in (("en", 0, "other"), ("en", 1, "one"), ("en", 2, "other"), ("fr", 0, "one"), ("fr", 1, "one"), ("fr", 2, "other"),
                                 ("fr", 1_000_000, "many"), ("es", 0, "other"), ("es", 1_000_000, "many"), ("de", 1_000_000, "other"),
                                 ("ja", 1, "other"), ("ko", 0, "other"), ("th", 5, "other"), ("id", 1, "other"), ("vi", 1, "other"), ("zh-Hans", 1, "other"),
                                 ("fil", 1, "one"), ("fil", 3, "one"), ("fil", 4, "other"), ("fil", 5, "one"), ("fil", 9, "other"), ("fil", 14, "other"),
                                 ("ar", 0, "zero"), ("ar", 1, "one"), ("ar", 2, "two"), ("ar", 3, "few"), ("ar", 10, "few"), ("ar", 11, "many"),
                                 ("ar", 99, "many"), ("ar", 100, "other"), ("ar", 102, "other"), ("ar", 103, "few"), ("it", 1, "one"), ("pt-BR", 0, "one"),
                                 ("pt-PT", 0, "other")):
            self.assertEqual(L.plural_category(tag, count), form, f"{tag} {count}")

    def test_a_negative_count_takes_the_form_of_its_magnitude(self):
        self.assertEqual(L.plural_category("en", -1), "one")
        self.assertEqual(L.plural_category("ar", -2), "two")

    def test_the_forms_a_catalog_must_give(self):
        self.assertEqual(L.plural_forms("ja"), ("other",))
        self.assertEqual(L.plural_forms("en"), ("one", "other"))
        self.assertEqual(L.plural_forms("ar"), ("zero", "one", "two", "few", "many", "other"))
        self.assertEqual(L.plural_forms("fr", required=False), ("one", "many", "other"))
        self.assertEqual(L.plural_forms("fr", required=True), ("one", "other"))

    def test_every_form_a_count_can_take_is_one_the_language_may_give(self):
        for x in REG.locales:
            for n in list(range(0, 1300)) + [10 ** 6, 2 * 10 ** 6, 12 * 10 ** 6]:
                self.assertIn(L.plural_category(x.tag, n), x.plural_all, f"{x.tag} {n}")
            for n in range(0, 1_000_000, 997):
                self.assertIn(L.plural_category(x.tag, n), x.plural_required, f"{x.tag} {n}")


class PlaceholderTest(unittest.TestCase):
    def test_names_in_order(self):
        self.assertEqual(L.placeholders("{a} then {b_2} and {a}"), (["a", "b_2", "a"], []))

    def test_doubled_braces_are_literal(self):
        self.assertEqual(L.placeholders("{{not}} {x}"), (["x"], []))

    def test_malformed_templates_are_reported(self):
        self.assertTrue(L.placeholders("open {x")[1])
        self.assertTrue(L.placeholders("close } here")[1])
        self.assertTrue(L.placeholders("{0}")[1])
        self.assertTrue(L.placeholders("{a b}")[1])
        self.assertTrue(L.placeholders("{}")[1])


class NumberTest(unittest.TestCase):
    def test_grouping_follows_the_language(self):
        self.assertEqual(L.format_number(loc("en"), 1234567), "1,234,567")
        self.assertEqual(L.format_number(loc("id"), 1234567), "1.234.567")
        self.assertEqual(L.format_number(loc("de"), 12345), "12.345")
        self.assertEqual(L.format_number(loc("fr"), 12345), "12" + loc("fr").group + "345")
        self.assertEqual(L.format_number(loc("en"), -1234), "-1,234")
        self.assertEqual(L.format_number(loc("en"), 999), "999")

    def test_a_language_may_leave_four_digit_numbers_alone(self):
        for x in REG.locales:
            digits = 3 + x.min_group
            self.assertEqual(L.format_number(x, 10 ** (digits - 1)).count(x.group) if x.group else 0, 1 if x.group else 0, x.tag)
            self.assertEqual(L.format_number(x, 10 ** (digits - 2)), str(10 ** (digits - 2)), x.tag)

    def test_render_fills_and_escapes(self):
        en = loc("en")
        self.assertEqual(L.render(en, "{count} items", count=12345), "12,345 items")
        self.assertEqual(L.render(en, "{{x}} {count}", count=3), "{x} 3")
        self.assertEqual(L.render(en, "{name} and {gone}", name="A"), "A and {gone}")
        self.assertEqual(L.render(en, "{name}", name=None), "")

    def test_an_id_is_never_grouped(self):
        self.assertEqual(L.render(loc("en"), "Item #{id}", id=123456), "Item #123456")
        self.assertEqual(L.render(loc("en"), "{count}", count=123456), "123,456")

    def test_a_boolean_is_not_a_number(self):
        self.assertEqual(L.render(loc("en"), "{x}", x=True), "True")

    def test_sample_values_are_the_worst_plausible(self):
        samples = L.sample_args(["count", "name", "names", "level"])
        self.assertEqual(samples["count"], 12345)
        self.assertGreater(len(samples["names"]), len(samples["name"]))


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.english = example_catalog("en")

    def findings(self, tag, edit):
        catalog = copy.deepcopy(example_catalog(tag))
        edit(catalog.texts)
        return catalog, L.catalog_findings(REG, self.english, catalog)

    def test_a_missing_key_is_found(self):
        key = next(iter(self.english.texts))
        catalog, found = self.findings("de", lambda t: t.pop(key))
        self.assertIn(("error", "missing", key), {(f.level, f.code, f.key) for f in found})
        tally = L.server_tally(REG, self.english, catalog)
        self.assertEqual((tally.missing, tally.translated, tally.complete), (1, tally.total - 1, False))

    def test_a_stale_key_is_found(self):
        catalog, found = self.findings("de", lambda t: t.update({"town.gone": "Weg"}))
        self.assertIn(("error", "stale", "town.gone"), {(f.level, f.code, f.key) for f in found})
        self.assertEqual(L.server_tally(REG, self.english, catalog).stale, 1)

    def test_a_shape_mismatch_is_found(self):
        plural = next(k for k in self.english.texts if self.english.is_plural(k))
        _, found = self.findings("de", lambda t: t.update({plural: "Ein Text"}))
        self.assertIn("shape", {f.code for f in found if f.key == plural})

    def test_a_missing_plural_form_is_found(self):
        plural = next(k for k in self.english.texts if self.english.is_plural(k))
        _, found = self.findings("ar", lambda t: t[plural].pop("few"))
        self.assertIn(("error", "plural"), {(f.level, f.code) for f in found if f.key == plural})

    def test_a_plural_form_the_language_never_uses_is_found(self):
        plural = next(k for k in self.english.texts if self.english.is_plural(k))
        _, found = self.findings("ja", lambda t: t[plural].update({"one": t[plural]["other"]}))
        self.assertIn(("error", "plural"), {(f.level, f.code) for f in found if f.key == plural})

    def test_a_renamed_placeholder_is_found(self):
        key = "example.stage"
        self.assertIn("level", L.placeholders(self.english.texts[key])[0])
        _, found = self.findings("de", lambda t: t.update({key: t[key].replace("{level}", "{lvl}")}))
        self.assertEqual({f.code for f in found if f.key == key and f.level == "error"}, {"placeholder"})
        self.assertEqual(sum(f.code == "placeholder" for f in found if f.key == key), 2)      # uses {lvl}, lacks {level}

    def test_a_catalog_of_an_unlisted_language_is_refused(self):
        found = L.catalog_findings(REG, self.english, L.Catalog("xx", {}))
        self.assertEqual([f.code for f in found], ["registry"])

    def test_the_catalog_parser_refuses_what_the_server_refuses(self):
        for doc in ([], {"": "x"}, {"k": ""}, {"k": 3}, {"k": {"few": "x"}}, {"k": {"other": ""}}, {"k": {"weird": "x", "other": "y"}}):
            with self.assertRaises(L.LocaleError, msg=repr(doc)):
                L.parse_catalog("en", doc)
        parsed = L.parse_catalog("en", {"a": "A", "b": {"one": "1", "other": "n"}})
        self.assertEqual(list(parsed.leaves()), [("a", "", "A"), ("b", "one", "1"), ("b", "other", "n")])
        self.assertEqual(parsed.forms("a"), {"": "A"})

    def test_a_duplicate_key_is_refused(self):
        import json
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "en.json"), "w", encoding="utf-8") as f:
                f.write('{"a": "1", "a": "2"}')
            with self.assertRaises(L.LocaleError):
                L.load_catalog("en", tmp)
            with open(os.path.join(tmp, "en.json"), "w", encoding="utf-8") as f:
                json.dump({"a": "1"}, f)
            self.assertEqual(L.load_catalog("en", tmp).texts, {"a": "1"})


class TextChecksTest(unittest.TestCase):
    def test_a_sound_text_has_no_findings(self):
        self.assertEqual(codes("fr", "Nouvelle qu" + chr(0xEA) + "te disponible : {name}.", "New quest available: {name}."), set())

    def test_not_normalized_text_is_an_error(self):
        self.assertIn("nfc", error_codes("fr", "Qu" + "e" + chr(0x301) + "te disponible"))
        self.assertNotIn("nfc", error_codes("fr", "Qu" + chr(0xE9) + "te disponible"))

    def test_control_characters_are_errors(self):
        self.assertIn("control", error_codes("en", "Quest" + chr(1)))
        self.assertIn("control", error_codes("en", "Quest" + chr(0xFFFD)))
        self.assertIn("control", error_codes("en", "Quest" + chr(0xFEFF)))
        self.assertIn("control", error_codes("en", "Two" + chr(10) + "lines"))
        self.assertNotIn("control", error_codes("en", "Two" + chr(10) + "lines", client=True))

    def test_whitespace_at_the_edges_or_doubled_is_an_error_except_for_a_joiner(self):
        self.assertIn("whitespace", error_codes("en", " Quest"))
        self.assertIn("whitespace", error_codes("en", "New  quest"))
        self.assertNotIn("whitespace", error_codes("en", ", ", key="list.separator"))
        self.assertNotIn("whitespace", error_codes("en", "Quest ", client=True))

    def test_directional_controls_belong_to_a_right_to_left_language_only(self):
        self.assertIn("bidi", error_codes("en", "Quest" + chr(0x200F)))
        arabic = u(0x0645, 0x0647, 0x0645, 0x0629, 0x0629)
        self.assertNotIn("bidi", error_codes("ar", arabic + chr(0x200F)))
        self.assertIn("bidi", error_codes("ar", chr(0x2067) + arabic))
        self.assertNotIn("bidi", error_codes("ar", chr(0x2067) + arabic + chr(0x2069)))

    def test_a_right_to_left_text_led_by_a_name_is_warned_about(self):
        arabic = u(0x0645, 0x0647, 0x0645, 0x0629, 0x0629)
        self.assertIn(("warning", "bidi-start"), codes("ar", "{shop} " + arabic))
        self.assertNotIn(("warning", "bidi-start"), codes("ar", "{count} " + arabic))
        self.assertNotIn(("warning", "bidi-start"), codes("ar", arabic + " {shop}"))

    def test_a_fragment_led_by_a_name_is_not_warned_about_but_a_line_of_its_own_still_is(self):
        arabic = u(0x0645, 0x0647, 0x0645, 0x0629, 0x0629)
        self.assertNotIn(("warning", "bidi-start"), codes("ar", "{shop} (+{count})", fragment=True))       # the parent's Arabic words set the line's direction
        self.assertIn(("warning", "bidi-start"), codes("ar", "{shop} " + arabic))                          # a text that stands alone is the line

    def test_the_registry_names_the_fragments_and_they_are_keys_of_the_english_catalog(self):
        self.assertIn("example.quantity", REG.fragments)
        english = example_catalog("en")
        self.assertEqual(sorted(set(REG.fragments) - set(english.texts)), [])
        stray = L.Registry(REG.default, REG.locales, REG.fragments + ("no.such_key",))
        codes_seen = {f.code for f in L.catalog_findings(stray, english, english)}
        self.assertIn("fragment", codes_seen)                                                              # a typo in the list is an error, not a silent exemption

    def test_the_arabic_catalog_is_free_of_warnings(self):
        english = example_catalog("en")
        arabic = example_catalog("ar")
        self.assertEqual([f for f in L.catalog_findings(REG, english, arabic) if f.level == "warning"], [])

    def test_a_malformed_placeholder_is_an_error(self):
        self.assertIn("format", error_codes("en", "Open {x"))
        self.assertIn("format", error_codes("en", "Stray } brace"))
        self.assertNotIn("format", error_codes("en", "Open {x", client=True))

    def test_a_text_in_the_wrong_script_looks_untranslated(self):
        self.assertIn("script", error_codes("ja", "Quest accepted from the guild"))
        self.assertIn("script", error_codes("zh-Hans", "Quest accepted from the guild"))
        self.assertIn("script", error_codes("ar", "Quest accepted from the guild"))
        self.assertIn("script", error_codes("th", "Quest accepted from the guild"))
        self.assertIn("script", error_codes("ko", "Quest accepted from the guild"))
        self.assertNotIn("script", error_codes("ja", u(0x30AF, 0x30A8, 0x30B9, 0x30C8, 0x53D7, 0x6CE8) + " {name}"))
        self.assertNotIn("script", error_codes("fr", "Qu" + chr(0xEA) + "te accept" + chr(0xE9) + "e"))

    def test_a_short_text_is_not_judged_by_its_script(self):
        self.assertNotIn("script", error_codes("ja", "HR"))

    def test_the_clients_own_markup_is_not_the_translation(self):
        korean = u(0xD658, 0xC601, 0xD569, 0xB2C8, 0xB2E4)
        self.assertNotIn("script", error_codes("ko", "$PLAYERNAME " + korean, client=True))
        self.assertNotIn("script", error_codes("ko", "<font color=red>" + korean + "</font>", client=True))

    def test_an_identical_text_is_a_warning_unless_the_registry_allows_it(self):
        self.assertIn(("warning", "identical"), codes("fr", "Quest accepted", "Quest accepted"))
        self.assertNotIn(("warning", "identical"), codes("fr", "Quest accepted", "Quest accepted", identical_ok=True))
        self.assertNotIn(("warning", "identical"), codes("en", "Quest accepted", "Quest accepted"))
        self.assertNotIn(("warning", "identical"), codes("fr", "HR", "HR"))

    def test_the_registry_names_the_keys_that_may_equal_the_english_text(self):
        self.assertIn("example.item", loc("id").identical_ok)
        self.assertEqual(loc("de").identical_ok, ())

    def test_japanese_must_survive_cp932(self):
        kana = u(0x30AF, 0x30A8, 0x30B9, 0x30C8)
        self.assertIn("cp932", error_codes("ja", kana + chr(0x301C)))         # the wave dash comes back as the fullwidth tilde
        self.assertIn("cp932", error_codes("ja", kana + chr(0x2212)))         # the minus sign comes back as the fullwidth hyphen-minus
        self.assertIn("cp932", error_codes("ja", kana + chr(0x2014)))         # the em dash has no CP932 bytes at all
        self.assertNotIn("cp932", error_codes("ja", kana + chr(0xFF5E)))
        self.assertNotIn("cp932", error_codes("ja", kana + chr(0xFF0D)))
        self.assertNotIn("cp932", error_codes("ja", kana + chr(0x2015)))
        self.assertNotIn("cp932", error_codes("ja", kana))
        message = next(f.message for f in L.text_findings(loc("ja"), "k", kana + chr(0x301C)) if f.code == "cp932")
        self.assertIn("U+FF5E", message)
        self.assertNotIn("cp932", error_codes("zh-Hans", u(0x4EFB, 0x52A1, 0x63A5, 0x53D7) + chr(0x301C)))

    def test_a_space_between_two_cjk_characters_is_a_warning(self):
        self.assertIn(("warning", "cjk-space"), codes("ja", u(0x30AF, 0x30A8, 0x30B9, 0x30C8) + " " + u(0x53D7, 0x6CE8)))
        self.assertNotIn(("warning", "cjk-space"), codes("ja", u(0x30AF, 0x30A8, 0x30B9, 0x30C8) + " {name}"))
        self.assertNotIn(("warning", "cjk-space"), codes("fr", "un deux trois"))

    def test_thai_marks_must_sit_on_a_consonant(self):
        word = u(0x0E20, 0x0E32, 0x0E23, 0x0E01, 0x0E34, 0x0E08, 0x0E43, 0x0E2B, 0x0E21, 0x0E48)
        self.assertEqual({c for c in error_codes("th", word)}, set())
        self.assertIn("thai-mark", error_codes("th", u(0x0E19, 0x0E4D, 0x0E32) + word))           # nikhahit + sara aa is sara am
        self.assertIn("thai-mark", error_codes("th", u(0x0E48, 0x0E01) + word))                    # a tone mark with nothing under it
        self.assertIn("thai-mark", error_codes("th", word + u(0x0E01, 0x0E40)))                    # a leading vowel with nothing after it
        self.assertIn("thai-mark", error_codes("th", word + u(0x0E01, 0x0E48, 0x0E49)))            # two tone marks in a row
        self.assertNotIn("thai-mark", error_codes("th", word + u(0x0E01, 0x0E33)))                 # the single sara am is right

    def test_a_long_thai_run_without_a_break_is_a_warning(self):
        self.assertIn(("warning", "break-run"), codes("th", u(0x0E01) * 50))
        self.assertNotIn(("warning", "break-run"), codes("th", (u(0x0E01) * 20 + " ") * 3))

    def test_an_unbreakable_run_is_measured_between_breaks_and_cjk(self):
        self.assertEqual(L.longest_unbreakable_run("ab cdef g"), 4)
        self.assertEqual(L.longest_unbreakable_run("abc-defgh"), 5)
        self.assertEqual(L.longest_unbreakable_run("ab" + u(0x30AF, 0x30A8) + "cde"), 3)
        self.assertEqual(L.longest_unbreakable_run("{name} x"), 1)

    def test_a_line_longer_than_a_chat_line_is_an_error(self):
        self.assertIn("length", error_codes("en", "word " * 40))
        self.assertIn(("warning", "length"), codes("en", ("word " * 25).strip()))
        self.assertNotIn("length", error_codes("en", "word " * 10))
        self.assertNotIn("length", error_codes("en", "word " * 40, client=True))

    def test_a_line_the_wire_cannot_carry_is_an_error(self):
        # the prototype uses a 400-byte line limit; Thai is one column and three UTF-8 bytes a letter, so a line can fit the width and not the wire
        self.assertEqual(L.MAX_WIRE_BYTES, 400)
        self.assertIn("wire", error_codes("th", u(0x0E2A) * 140))
        self.assertNotIn("length", error_codes("th", u(0x0E2A) * 140))
        self.assertNotIn("wire", error_codes("th", u(0x0E2A) * 100))
        self.assertNotIn("wire", error_codes("th", u(0x0E2A) * 140, client=True))

    def test_a_placeholder_is_measured_at_its_worst(self):
        text = ("word " * 12).strip() + " {names}"          # 59 columns of text plus a 40 character list of names
        self.assertIn(("warning", "length"), codes("en", text + " " + "word " * 4 + "end"))
        self.assertNotIn(("warning", "length"), codes("en", ("word " * 12).strip()))

    def test_a_translation_far_wider_than_the_english_is_a_warning(self):
        self.assertIn(("warning", "expansion"), codes("de", "Neue Quest steht ab sofort zur Verfuegung " * 2 + "jetzt", "New quest available"))
        self.assertNotIn(("warning", "expansion"), codes("de", "Neue Quest verfuegbar", "New quest available"))
        self.assertNotIn(("warning", "expansion"), codes("de", "Neue Quest steht ab sofort zur Verfuegung " * 2 + "jetzt", "New quest"))   # too short a source to judge

    def test_display_width_counts_wide_characters_twice_and_marks_not_at_all(self):
        self.assertEqual(L.display_width("abc"), 3)
        self.assertEqual(L.display_width(u(0x30AF, 0x30A8)), 4)
        self.assertEqual(L.display_width("e" + chr(0x301)), 1)
        self.assertEqual(L.display_width(u(0x0E01, 0x0E48)), 1)

    def test_script_of_names_the_script_of_a_letter(self):
        for ch, script in (("a", "Latn"), (chr(0xE9), "Latn"), (chr(0x1EA1), "Latn"), (chr(0x4EFB), "Hani"), (chr(0x30AF), "Kana"), (chr(0xD658), "Hang"),
                           (chr(0x0E01), "Thai"), (chr(0x0645), "Arab")):
            self.assertEqual(L.script_of(ch), script, hex(ord(ch)))
        for ch in ("1", " ", ".", chr(0x0E48), chr(0x301)):
            self.assertIsNone(L.script_of(ch), hex(ord(ch)))


class TallyTest(unittest.TestCase):
    def test_a_translation_memory_is_counted_against_its_source(self):
        sources = {"a": "A", "b": "B", "c": "C"}
        t = L.tm_tally(sources, {"a": "x", "b": "y", "z": "stale"}, lambda source, text: [])
        self.assertEqual((t.total, t.translated, t.missing, t.stale, t.format_errors), (3, 2, 1, 1, 0))
        self.assertFalse(t.complete)
        self.assertAlmostEqual(t.ratio, 2 / 3)

    def test_an_entry_that_fails_its_check_is_not_translated(self):
        t = L.tm_tally({"a": "A", "b": "B"}, {"a": "x", "b": "bad"}, lambda source, text: ["nope"] if text == "bad" else [])
        self.assertEqual((t.translated, t.format_errors, t.complete), (1, 1, False))

    def test_a_complete_memory(self):
        t = L.tm_tally({"a": "A"}, {"a": "x"}, lambda source, text: [])
        self.assertTrue(t.complete)
        self.assertEqual(t.ratio, 1.0)

    def test_nothing_to_translate_is_not_complete(self):
        self.assertFalse(L.tm_tally({}, {}, lambda s, t: []).complete)

class BlockerTest(unittest.TestCase):
    DONE = L.Tally(10, 10, 0, 0, 0)

    def blockers(self, tag, server=DONE, client=None, glyphs=0):
        return L.locale_blockers(loc(tag), server, {"dialogue": self.DONE} if client is None else client, glyphs)

    def test_english_is_complete_when_everything_is_measured_and_sound(self):
        self.assertEqual(self.blockers("en"), [])

    def test_a_machine_draft_is_never_complete(self):
        self.assertTrue(any(b.startswith("review:") for b in self.blockers("de")))

    def test_an_undecided_variant_is_a_blocker(self):
        self.assertTrue(any(b.startswith("variant:") for b in self.blockers("pt-BR")))
        self.assertFalse(any(b.startswith("variant:") for b in self.blockers("de")))

    def test_unmeasured_is_not_complete(self):
        self.assertIn("glyphs: not measured", self.blockers("en", glyphs=None))
        self.assertIn("server text: not measured", self.blockers("en", server=None))
        self.assertTrue(any("not measured" in b for b in self.blockers("fr", client={"dialogue": None})))

    def test_untranslated_client_text_is_a_blocker_but_the_source_language_has_none(self):
        half = L.Tally(10, 5, 5, 0, 0)
        self.assertTrue(any("5 of 10" in b for b in self.blockers("fr", client={"dialogue": half})))
        self.assertFalse(any(b.startswith("client text") for b in self.blockers("zh-Hans", client={"dialogue": half})))

    def test_an_incomplete_server_catalog_is_a_blocker(self):
        self.assertTrue(any(b.startswith("server text: 9 of 10") for b in self.blockers("en", server=L.Tally(10, 9, 1, 0, 0))))

    def test_missing_glyphs_are_counted_and_named(self):
        self.assertTrue(any("lack 3 characters" in b for b in self.blockers("ko", glyphs=3)))
        named = [b for b in self.blockers("fr", glyphs=(NBSP,)) if b.startswith("glyphs")]
        self.assertEqual(len(named), 1)
        self.assertIn("U+00A0", named[0])

    def test_glyph_names_are_cut_short(self):
        self.assertEqual(L.glyph_names(tuple("abcdefgh"), limit=3), "U+0061 U+0062 U+0063 ...")


if __name__ == "__main__":
    unittest.main()
