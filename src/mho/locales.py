"""Offline checks for localized text and catalogs.

Checks cover placeholder parity, integer plurals, Unicode normalization,
directional controls, character scripts, and estimated text width.
Callers supply a locale registry and their own catalogs.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

BRIEF_LABELS = ("EN", "ID", "JP", "KR", "PH", "CN", "FR", "VN", "PT", "TH", "DE", "SA", "IT", "ES")
PLURAL_FORMS = ("zero", "one", "two", "few", "many", "other")
REVIEW_STATES = ("canonical", "draft", "reviewed")
# The client's own text is Simplified Chinese: that locale needs no client translation, it IS the source.
CLIENT_SOURCE_TAG = "zh-Hans"

JOINER_PREFIX = "list."   # the keys that join items ("list.separator" is ", "): they keep a space at the end on purpose
NUMERIC_PLACEHOLDERS = frozenset({"count", "level", "id", "rank", "from", "to", "system"})     # filled with digits, which take the direction of the text around them
MAX_LINE = 160            # the prototype's line width limit
MAX_WIRE_BYTES = 400      # the prototype's UTF-8 byte limit
WARN_LINE = 120
EXPANSION_WARN = 2.2      # a text this many times wider than the English one is at risk of truncation in a fixed-width widget


class LocaleError(ValueError):
    """A registry, catalog or vector file that is not well formed (the message names the file and the key)."""


@dataclass(frozen=True)
class Finding:
    """One problem (``error``) or risk (``warning``) with a locale's text: the catalog ``key`` and, for a plural text, the ``form`` it is about."""
    level: str
    tag: str
    key: str
    code: str
    message: str
    form: str = ""

    def __str__(self) -> str:
        where = f"{self.key}.{self.form}" if self.form else self.key
        return f"{self.level:7} {self.tag:8} {where:32} {self.code}: {self.message}"


# -- reading the files (strictly: a duplicate key or a byte order mark is an error, not something to shrug at) ----------------------------

def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise LocaleError(f"'{key}' is given twice")
        seen[key] = value
    return seen


def read_json(path: str):
    """A JSON file, strictly UTF-8 without a byte order mark, with no key given twice."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise LocaleError(f"{os.path.basename(path)}: has a byte order mark")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except UnicodeDecodeError as e:
        raise LocaleError(f"{os.path.basename(path)}: not UTF-8 ({e})") from e
    except (json.JSONDecodeError, LocaleError) as e:
        raise LocaleError(f"{os.path.basename(path)}: {e}") from e


@dataclass(frozen=True)
class Locale:
    """One locale of ``locales.json``."""
    tag: str
    label: str
    english: str
    native: str
    script: str
    rtl: bool
    aliases: tuple[str, ...]
    plural_required: tuple[str, ...]
    plural_all: tuple[str, ...]
    group: str
    decimal: str
    min_group: int
    review: str
    variant_decided: bool
    variant_note: str
    identical_ok: tuple[str, ...] = ()       # keys whose text is rightly the same as the English one (a loanword: "Item #{id}")


@dataclass(frozen=True)
class Registry:
    default: str
    locales: tuple[Locale, ...]
    fragments: tuple[str, ...] = ()          # keys whose text is only ever an argument of another text ("{shop} (+{count})" inside "New shop stock: {shops}.")

    def get(self, tag: str) -> Locale | None:
        """The locale with exactly this tag (case does not matter), or None."""
        wanted = (tag or "").strip().lower()
        return next((loc for loc in self.locales if loc.tag.lower() == wanted), None)

    def by_label(self, label: str) -> Locale | None:
        return next((loc for loc in self.locales if loc.label == label), None)

    def resolve(self, requested: str) -> str | None:
        """The registry tag for a tag a caller may say (``zh-CN``, ``pt``, ``en_US``, ``tl``), with progressively less specific subtags."""
        if not requested or not requested.strip():
            return None
        tag = requested.strip().replace("_", "-")
        candidate = tag
        while candidate:
            if (exact := self.get(candidate)) is not None:
                return exact.tag
            for loc in self.locales:
                if any(a.lower() == candidate.lower() for a in loc.aliases):
                    return loc.tag
            candidate = candidate.rpartition("-")[0]
        language = tag.partition("-")[0].lower()
        return next((loc.tag for loc in self.locales if loc.tag.partition("-")[0].lower() == language), None)


def load_registry(path: str) -> Registry:
    doc = read_json(path)
    try:
        locales = []
        for e in doc["locales"]:
            n = e["numbers"]
            v = e["variant"]
            locales.append(Locale(
                tag=e["tag"], label=e["label"], english=e["english"], native=e["native"], script=e["script"], rtl=e["dir"] == "rtl",
                aliases=tuple(e["aliases"]), plural_required=tuple(e["plural_required"]), plural_all=tuple(e["plural_all"]),
                group=n["group"], decimal=n["decimal"], min_group=int(n["min_group"]), review=e["review"],
                variant_decided=bool(v["decided"]), variant_note=v["note"], identical_ok=tuple(e.get("identical_ok", ()))))
        return Registry(doc["default"], tuple(locales), tuple(doc.get("fragments", ())))
    except (KeyError, TypeError) as e:
        raise LocaleError(f"{os.path.basename(path)}: missing or malformed {e}") from e


def registry_problems(reg: Registry) -> list[str]:
    """What is wrong with the list of languages itself (empty when it is sound)."""
    out: list[str] = []
    labels = [loc.label for loc in reg.locales]
    if sorted(labels) != sorted(BRIEF_LABELS):
        out.append(f"the labels are {labels}, the brief's are {list(BRIEF_LABELS)}")
    if reg.get(reg.default) is None:
        out.append(f"the default '{reg.default}' is not listed")
    names: dict[str, str] = {}
    for loc in reg.locales:
        for name in (loc.tag, *loc.aliases):
            if (other := names.setdefault(name.lower(), loc.tag)) != loc.tag:
                out.append(f"'{name}' names both {other} and {loc.tag}")
        if loc.review not in REVIEW_STATES:
            out.append(f"{loc.tag}: review '{loc.review}' is not one of {REVIEW_STATES}")
        if loc.tag == reg.default and loc.review != "canonical":
            out.append(f"{loc.tag}: the default language must be the canonical source")
        if loc.tag != reg.default and loc.review == "canonical":
            out.append(f"{loc.tag}: only the default language is canonical")
        if tuple(plural_forms(loc.tag, required=True)) != loc.plural_required:
            out.append(f"{loc.tag}: plural_required {list(loc.plural_required)} is not what the rules require {plural_forms(loc.tag, required=True)}")
        if tuple(plural_forms(loc.tag, required=False)) != loc.plural_all:
            out.append(f"{loc.tag}: plural_all {list(loc.plural_all)} is not what the rules allow {plural_forms(loc.tag, required=False)}")
        if loc.min_group < 1:
            out.append(f"{loc.tag}: min_group must be at least 1")
    return out


# -- integer plural rules ---------------

def _language(tag: str) -> str:
    return re.split(r"[-_]", tag.strip(), maxsplit=1)[0].lower()


def _rule(tag: str) -> str:
    language = _language(tag)
    if language in ("ja", "ko", "zh", "vi", "th", "id"):
        return "other"
    if language in ("en", "de"):
        return "one"
    if language in ("it", "es"):
        return "one_many"
    if language == "fr":
        return "zero_one_many"
    if language == "pt":
        return "one_many" if tag.strip().upper().endswith("-PT") else "zero_one_many"
    if language in ("fil", "tl"):
        return "fil"
    if language == "ar":
        return "ar"
    return "unknown"


def plural_forms(tag: str, required: bool = True) -> tuple[str, ...]:
    """The forms a catalog must give (``required``: every form a count below a million takes) or may give (all of them) for a plural text."""
    rule = _rule(tag)
    if rule == "other":
        return ("other",)
    if rule == "ar":
        return ("zero", "one", "two", "few", "many", "other")
    if not required and rule in ("one_many", "zero_one_many"):
        return ("one", "many", "other")
    return ("one", "other")


def plural_category(tag: str, count: int) -> str:
    """The CLDR plural form of a whole ``count`` in the locale (a locale the rules do not know is treated as English)."""
    n = abs(int(count))
    rule = _rule(tag)
    millions = n != 0 and n % 1_000_000 == 0
    if rule == "other":
        return "other"
    if rule in ("one", "unknown"):
        return "one" if n == 1 else "other"
    if rule == "one_many":
        return "one" if n == 1 else ("many" if millions else "other")
    if rule == "zero_one_many":
        return "one" if n <= 1 else ("many" if millions else "other")
    if rule == "fil":
        return "one" if n in (1, 2, 3) or n % 10 not in (4, 6, 9) else "other"
    if n == 0:                                    # Arabic
        return "zero"
    if n == 1:
        return "one"
    if n == 2:
        return "two"
    r = n % 100
    return "few" if 3 <= r <= 10 else ("many" if 11 <= r <= 99 else "other")


def vector_problems(vectors: Mapping, reg: Registry) -> list[str]:
    """Where the rules above disagree with the written contract, and any locale the contract does not cover."""
    out: list[str] = []
    for tag, forms in vectors.items():
        for form, counts in forms.items():
            for n in counts:
                got = plural_category(tag, n)
                if got != form:
                    out.append(f"{tag}: {n} is '{got}', the vectors say '{form}'")
    for loc in reg.locales:
        if loc.tag not in vectors:
            out.append(f"{loc.tag}: no plural vectors")
    return out


# -- text: placeholders, numbers, rendering ---------------------------------------------------------------------------------------

def placeholders(text: str) -> tuple[list[str], list[str]]:
    """``({names in order}, [format errors])`` of a template: ``{name}`` fills, ``{{`` and ``}}`` are literal braces; anything else with a brace is an error."""
    names: list[str] = []
    errors: list[str] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "{":
            if text[i + 1:i + 2] == "{":
                i += 2
                continue
            close = text.find("}", i + 1)
            if close < 0:
                errors.append("an opening brace is never closed")
                break
            name = text[i + 1:close]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                names.append(name)
            else:
                errors.append(f"'{{{name}}}' is not a placeholder name")
            i = close + 1
            continue
        if c == "}":
            if text[i + 1:i + 2] == "}":
                i += 2
                continue
            errors.append("a closing brace has no opening brace")
        i += 1
    return names, errors


def format_number(loc: Locale, value: int) -> str:
    """A whole number the way the language writes it (mirrors ``Loc.Number``)."""
    digits = str(abs(int(value)))
    if loc.group and len(digits) >= 3 + loc.min_group:
        head = len(digits) % 3 or 3
        digits = digits[:head] + "".join(loc.group + digits[i:i + 3] for i in range(head, len(digits), 3))
    return ("-" if value < 0 else "") + digits


def render(loc: Locale, template: str, **args: object) -> str:
    """The template with its placeholders filled in (mirrors ``Loc.Format``; a name that is not given stays in the text)."""
    out: list[str] = []
    i = 0
    while i < len(template):
        c = template[i]
        if c == "{" and template[i + 1:i + 2] == "{":
            out.append("{")
            i += 2
        elif c == "}" and template[i + 1:i + 2] == "}":
            out.append("}")
            i += 2
        elif c == "{" and (close := template.find("}", i + 1)) > 0:
            name = template[i + 1:close]
            value = args.get(name)
            if name not in args:
                out.append("{" + name + "}")
            elif isinstance(value, int) and not isinstance(value, bool):
                out.append(str(value) if name == "id" else format_number(loc, value))
            else:
                out.append("" if value is None else str(value))
            i = close + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def sample_args(names: Iterable[str]) -> dict[str, object]:
    """Worst-plausible values for the placeholders of a text (a long name, a five digit count) -- what the length checks measure with."""
    samples: dict[str, object] = {}
    for name in names:
        if name in ("names", "shops", "reasons"):
            samples[name] = "Rathalos Nest, Jaggi Camp, Apceros Field"
        elif name in ("name", "shop", "from", "to"):
            samples[name] = "Rathalos Nest"
        else:
            samples[name] = 12345
    return samples


# -- catalogs ---------------------------------------------------------------------------------------------------------------------

@dataclass
class Catalog:
    """The texts of one language, keyed by message name and optionally plural form."""
    tag: str
    texts: dict[str, str | dict[str, str]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.texts)

    def is_plural(self, key: str) -> bool:
        return isinstance(self.texts.get(key), dict)

    def forms(self, key: str) -> dict[str, str]:
        """``{form: text}`` of a key (a plain text is ``{"": text}``)."""
        value = self.texts[key]
        return dict(value) if isinstance(value, dict) else {"": value}

    def leaves(self) -> Iterable[tuple[str, str, str]]:
        """``(key, form, text)`` for every string of the catalog (form is '' for a plain text)."""
        for key, value in self.texts.items():
            if isinstance(value, dict):
                for form, text in value.items():
                    yield key, form, text
            else:
                yield key, "", value


def parse_catalog(tag: str, doc: object) -> Catalog:
    """A catalog from its parsed JSON: refuses what ``LocaleCatalog.Parse`` refuses (an empty key or text, an unknown plural form, no ``other``)."""
    if not isinstance(doc, dict):
        raise LocaleError(f"{tag}: the catalog is not a JSON object")
    catalog = Catalog(tag)
    for key, value in doc.items():
        if not key:
            raise LocaleError(f"{tag}: an empty key")
        if isinstance(value, str):
            if not value:
                raise LocaleError(f"{tag}: '{key}' is empty")
            catalog.texts[key] = value
        elif isinstance(value, dict):
            forms: dict[str, str] = {}
            for form, text in value.items():
                if form not in PLURAL_FORMS:
                    raise LocaleError(f"{tag}: '{key}' has a plural form '{form}' that is unknown")
                if not isinstance(text, str) or not text:
                    raise LocaleError(f"{tag}: '{key}.{form}' is empty or not a string")
                forms[form] = text
            if "other" not in forms:
                raise LocaleError(f"{tag}: '{key}' has no 'other' form")
            catalog.texts[key] = forms
        else:
            raise LocaleError(f"{tag}: '{key}' is neither a string nor an object of plural forms")
    return catalog


def load_catalog(tag: str, directory: str) -> Catalog:
    return parse_catalog(tag, read_json(os.path.join(directory, f"{tag}.json")))


_SCRIPTS = (
    ("Hani", ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FA1F))),
    ("Kana", ((0x3040, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9F))),
    ("Hang", ((0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7FF))),
    ("Thai", ((0x0E01, 0x0E5B),)),
    ("Arab", ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))),
    ("Latn", ((0x41, 0x5A), (0x61, 0x7A), (0xAA, 0xAA), (0xBA, 0xBA), (0xC0, 0x24F), (0x1E00, 0x1EFF))),
)
EXPECTED = {"Latn": {"Latn"}, "Jpan": {"Hani", "Kana"}, "Kore": {"Hang"}, "Hans": {"Hani"}, "Thai": {"Thai"}, "Arab": {"Arab"}}
_BIDI_CONTROLS = {chr(c) for c in (0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069)}
_BIDI_OPEN = {chr(c) for c in (0x202A, 0x202B, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068)}
_BIDI_CLOSE = {chr(c) for c in (0x202C, 0x2069)}
_BREAKS = {" ", chr(9), "-", chr(0x200B), chr(0x00AD)}                   # where a line may break (a zero-width space and a soft hyphen are invisible)
_BANNED = {chr(0xFFFD), chr(0xFEFF)}                                          # the replacement character (a decoding accident) and a stray byte order mark
_CJK_SPACE = re.compile(f"(?<=[{chr(0x3040)}-{chr(0x30FF)}{chr(0x3400)}-{chr(0x9FFF)}]) (?=[{chr(0x3040)}-{chr(0x30FF)}{chr(0x3400)}-{chr(0x9FFF)}])")
_THAI_CONSONANTS = {chr(c) for c in range(0x0E01, 0x0E2F)}
_SARA_AM_PARTS = chr(0x0E4D) + chr(0x0E32)                                    # nikhahit + sara aa: the two halves of sara am (U+0E33)
_THAI_ABOVE_BELOW = set(chr(c) for c in (0x0E31, 0x0E34, 0x0E35, 0x0E36, 0x0E37, 0x0E38, 0x0E39, 0x0E3A, 0x0E47, 0x0E48, 0x0E49, 0x0E4A, 0x0E4B, 0x0E4C, 0x0E4D, 0x0E4E))
_THAI_TONES = set(chr(c) for c in (0x0E48, 0x0E49, 0x0E4A, 0x0E4B))
_THAI_LEADING = set(chr(c) for c in range(0x0E40, 0x0E45))                 # vowels written before the consonant they follow in speech


def script_of(ch: str) -> str | None:
    """The script of a letter ('Hani', 'Kana', 'Hang', 'Thai', 'Arab', 'Latn'), or None for a digit, a mark, punctuation, a space."""
    code = ord(ch)
    for name, spans in _SCRIPTS:
        if any(lo <= code <= hi for lo, hi in spans):
            return name if unicodedata.category(ch)[0] == "L" else None
    return None


def display_width(text: str) -> int:
    """Columns the text takes in a fixed-pitch layout: East Asian wide and full-width characters count two."""
    return sum(0 if unicodedata.combining(c) or unicodedata.category(c) in ("Mn", "Cf") else (2 if unicodedata.east_asian_width(c) in ("W", "F") else 1)
               for c in text)


def _outside_placeholders(text: str) -> str:
    return re.sub(r"\{[^{}]*\}", "", text.replace("{{", "").replace("}}", ""))


_TOKENS = re.compile(r"<[^<>]+>|\$[A-Za-z0-9_]+|%\d*[sdif]")         # the client's own markup, key tokens and format codes: Latin letters that are not the translation


def _letters(text: str) -> list[str]:
    return [s for ch in _TOKENS.sub("", _outside_placeholders(text)) if (s := script_of(ch))]


def longest_unbreakable_run(text: str) -> int:
    """The longest stretch of characters with no place a line may break: a space, a hyphen, a zero-width space, or beside a CJK character (which
    may break almost anywhere). A Thai sentence is written without spaces, so it is one run until the client's own line breaker decides otherwise."""
    best = run = 0
    for ch in _outside_placeholders(text):
        wide = unicodedata.east_asian_width(ch) in ("W", "F")
        if ch in _BREAKS or wide:
            best, run = max(best, run), 0
        else:
            run += 1
    return max(best, run)


def text_findings(loc: Locale, key: str, text: str, english: str | None = None, *, form: str = "", identical_ok: bool = False,
                  client: bool = False, fragment: bool = False) -> list[Finding]:
    """The checks a translated string must pass in ``loc`` (``english`` is the source it translates; None for the source language itself).

    Set ``client`` for dialogue that can span lines and uses tokens validated by the calling application.
    Set ``fragment`` for text inserted into a larger line that establishes the reading direction.
    """
    tag = loc.tag
    out: list[Finding] = []

    def add(level: str, code: str, message: str) -> None:
        out.append(Finding(level, tag, key, code, message, form))

    if not client and ("  " in text or (text != text.strip() and not key.startswith(JOINER_PREFIX))):
        add("error", "whitespace", "leading or trailing space, or a doubled space")
    if not unicodedata.is_normalized("NFC", text):
        add("error", "nfc", "not in Unicode normalization form C (a precomposed letter is written as a base and a combining mark)")
    for ch in sorted(set(text)):
        category = unicodedata.category(ch)
        if ch in _BANNED or (category in ("Cc", "Cs", "Co", "Cn") and not (client and ch in "\n\r\t")):
            add("error", "control", f"contains U+{ord(ch):04X} ({unicodedata.name(ch, category)}), which no text may carry")
    bidi = [ch for ch in text if ch in _BIDI_CONTROLS]
    if bidi and not loc.rtl:
        add("error", "bidi", "a left-to-right language carries directional control characters")
    if bidi:
        opened = sum(ch in _BIDI_OPEN for ch in text)
        closed = sum(ch in _BIDI_CLOSE for ch in text)
        if opened != closed:
            add("error", "bidi", f"{opened} directional openers and {closed} closers")
    lead = re.match(r"[ (]*\{([A-Za-z_]\w*)\}", text) if loc.rtl and not fragment else None
    if lead and lead.group(1) not in NUMERIC_PLACEHOLDERS:
        add("warning", "bidi-start", f"starts with {{{lead.group(1)}}}: a left-to-right name would set the direction of the whole line (UNKNOWN in the client)")

    if not client:
        for message in placeholders(text)[1]:
            add("error", "format", message)

    letters = _letters(text)
    expected = EXPECTED[loc.script]
    if len(letters) >= 4:
        share = sum(s in expected for s in letters) / len(letters)
        if share < 0.6:
            add("error", "script", f"only {share:.0%} of its letters are {'/'.join(sorted(expected))}: it looks untranslated")
    if english is not None and loc.tag != "en" and not identical_ok and text == english and len(_letters(english)) >= 4:
        add("warning", "identical", "the same as the English text")

    if loc.script == "Jpan":                       # Japanese text meets the Windows ANSI code page (CP932) at file names, the IME and old tools
        try:
            back = text.encode("cp932").decode("cp932")
        except UnicodeEncodeError as e:
            bad = text[e.start:e.end]
            add("error", "cp932", f"'{bad}' (U+{ord(bad[0]):04X}) has no CP932 byte sequence")
        else:
            if back != text:                       # CP932 is one to one for a character, so the first difference is the first changed character
                at = next(i for i, (a, b) in enumerate(zip(text, back)) if a != b)
                add("error", "cp932", f"'{text[at]}' (U+{ord(text[at]):04X}) comes back as U+{ord(back[at]):04X} across the CP932 boundary"
                                      + (" (the wave dash is the fullwidth tilde there)" if text[at] == chr(0x301C) else ""))
    if loc.script in ("Jpan", "Hans") and _CJK_SPACE.search(text):
        add("warning", "cjk-space", "a space between two CJK characters (Japanese and Chinese are not word-spaced)")
    if loc.script == "Thai":
        for m in re.finditer(_SARA_AM_PARTS, text):
            add("error", "thai-mark", f"nikhahit + sara aa at {m.start()} should be the single sara am U+0E33")
            break
        for i, ch in enumerate(text):
            if ch in _THAI_ABOVE_BELOW and (i == 0 or not (text[i - 1] in _THAI_CONSONANTS or text[i - 1] in _THAI_ABOVE_BELOW)):
                add("error", "thai-mark", f"the combining mark U+{ord(ch):04X} at {i} has no consonant to sit on")
                break
            if ch in _THAI_TONES and i + 1 < len(text) and text[i + 1] in _THAI_TONES:
                add("error", "thai-mark", f"two tone marks in a row at {i}")
                break
        for i, ch in enumerate(text):
            after = text[i + 1:i + 2]
            if ch in _THAI_LEADING and (not after or after == " " or chr(0x0E30) <= after <= chr(0x0E5B)):
                add("error", "thai-mark", f"the leading vowel U+{ord(ch):04X} at {i} is not followed by a consonant")
                break
        run = longest_unbreakable_run(text)
        if run > 40:
            add("warning", "break-run", f"{run} characters with no break opportunity: the client's line breaker must know Thai words (UNKNOWN)")

    if client:
        return out
    names, _ = placeholders(text)
    filled = render(loc, text, **sample_args(names))
    width = display_width(filled)
    if width > MAX_LINE:
        add("error", "length", f"{width} columns filled with long names; a chat line takes {MAX_LINE}")
    elif width > WARN_LINE:
        add("warning", "length", f"{width} columns filled with long names (over {WARN_LINE})")
    wire = len(filled.encode("utf-8"))
    if wire > MAX_WIRE_BYTES:
        add("error", "wire", f"{wire} bytes of UTF-8 filled with long names; a chat line carries {MAX_WIRE_BYTES} (the server would cut it)")
    if english is not None and loc.tag != "en":
        en_width = display_width(render(loc, english, **sample_args(placeholders(english)[0])))
        if en_width >= 12 and width / en_width > EXPANSION_WARN:
            add("warning", "expansion", f"{width / en_width:.1f} times as wide as the English text ({width} against {en_width} columns)")
    return out


def catalog_findings(reg: Registry, english: Catalog, catalog: Catalog) -> list[Finding]:
    """Everything wrong with one language's catalog against the English one (keys, shapes, plural forms, placeholders, every text check)."""
    loc = reg.get(catalog.tag)
    if loc is None:
        return [Finding("error", catalog.tag, "-", "registry", "the language is not in locales.json")]
    out: list[Finding] = []
    for key in sorted(set(reg.fragments) - set(english.texts)):
        out.append(Finding("error", loc.tag, key, "fragment", "named a fragment in locales.json, but no such key is in the English catalog"))
    for key in sorted(set(catalog.texts) - set(english.texts)):
        out.append(Finding("error", loc.tag, key, "stale", "a key the English catalog does not have"))
    for key in english.texts:
        if key not in catalog.texts:
            out.append(Finding("error", loc.tag, key, "missing", "a key the English catalog has"))
            continue
        en_plural, plural = english.is_plural(key), catalog.is_plural(key)
        if en_plural != plural:
            out.append(Finding("error", loc.tag, key, "shape", "plural in one catalog and plain in the other"))
            continue
        en_forms = english.forms(key)
        wanted = {n for text in en_forms.values() for n in placeholders(text)[0]}
        for form, text in catalog.forms(key).items():
            english_text = en_forms.get(form) or en_forms.get("other") or next(iter(en_forms.values()))
            out.extend(text_findings(loc, key, text, english_text, form=form, identical_ok=key in loc.identical_ok, fragment=key in reg.fragments))
            names = set(placeholders(text)[0])
            for name in sorted(names - wanted - ({"count"} if plural else set())):
                out.append(Finding("error", loc.tag, key, "placeholder", f"uses {{{name}}}, which the English text does not", form))
            for name in sorted(wanted - names - ({"count"} if plural else set())):
                out.append(Finding("error", loc.tag, key, "placeholder", f"lacks {{{name}}}", form))
        if plural:
            have = set(catalog.forms(key))
            for form in sorted(set(loc.plural_required) - have, key=PLURAL_FORMS.index):
                out.append(Finding("error", loc.tag, key, "plural", f"has no '{form}' form, which {loc.tag} needs"))
            for form in sorted(have - set(loc.plural_all), key=PLURAL_FORMS.index):
                out.append(Finding("error", loc.tag, key, "plural", f"has a '{form}' form, which {loc.tag} never uses"))
    return out


# -- tallies and what stands between a locale and "complete" ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tally:
    """How much of a body of text a locale has: ``total`` strings to translate, ``translated`` of them present and sound, ``missing``, ``stale``
    (present but no longer in the source), ``format_errors`` (present but failing a check), ``identical`` (present but the same as the source)."""
    total: int
    translated: int
    missing: int
    stale: int
    format_errors: int
    identical: int = 0

    @property
    def complete(self) -> bool:
        return self.total > 0 and self.translated == self.total and not (self.missing or self.stale or self.format_errors)

    @property
    def ratio(self) -> float:
        return self.translated / self.total if self.total else 1.0


def server_tally(reg: Registry, english: Catalog, catalog: Catalog) -> Tally:
    """Strings of the server catalog: a plural key counts once per key (its forms are checked, not counted)."""
    findings = catalog_findings(reg, english, catalog)
    errors = [f for f in findings if f.level == "error"]
    bad = {f.key for f in errors if f.code not in ("missing", "stale")} & set(english.texts) & set(catalog.texts)
    missing = sum(1 for k in english.texts if k not in catalog.texts)
    stale = sum(1 for k in catalog.texts if k not in english.texts)
    identical = len({f.key for f in findings if f.code == "identical"})
    translated = sum(1 for k in english.texts if k in catalog.texts and k not in bad)
    return Tally(len(english.texts), translated, missing, stale, len(bad), identical)


def tm_tally(sources: Mapping[str, str], entries: Mapping[str, str], check) -> Tally:
    """A client text target: ``sources`` is ``{key: Chinese}`` from the client, ``entries`` the translation memory ``{key: text}``, ``check(source, text)``
    returns the problems of one entry."""
    missing = sum(1 for k in sources if k not in entries)
    stale = sum(1 for k in entries if k not in sources)
    errors = sum(1 for k, text in entries.items() if k in sources and check(sources[k], text))
    translated = sum(1 for k, text in entries.items() if k in sources and not check(sources[k], text))
    return Tally(len(sources), translated, missing, stale, errors)


def glyph_names(chars: Sequence[str], limit: int = 6) -> str:
    """``U+00A0 U+00E7 ...``: characters by code point (a space or a combining mark cannot be read from the character itself)."""
    return " ".join(f"U+{ord(c):04X}" for c in chars[:limit]) + (" ..." if len(chars) > limit else "")


def locale_blockers(loc: Locale, server: Tally | None, client: Mapping[str, Tally | None], glyphs_missing: int | Sequence[str] | None) -> list[str]:
    """Every reason this locale is not release-complete, in words; empty means complete. ``None`` for a measure means it could not be taken here
    (no client on this machine): that is a blocker too -- unmeasured is not complete. ``glyphs_missing``: how many characters the shipped fonts lack,
    or the characters themselves (then they are named)."""
    out: list[str] = []
    if loc.review == "draft":
        out.append("review: a machine draft, no native-speaker review")
    elif loc.review != "canonical" and loc.review != "reviewed":
        out.append(f"review: state '{loc.review}'")
    if not loc.variant_decided:
        out.append("variant: the brief leaves the choice to the owner, who has not made it")
    if server is None:
        out.append("server text: not measured")
    elif not server.complete:
        out.append(f"server text: {server.translated} of {server.total} keys sound "
                   f"({server.missing} missing, {server.stale} stale, {server.format_errors} with errors)")
    if loc.tag != CLIENT_SOURCE_TAG:
        for target, tally in client.items():
            if tally is None:
                out.append(f"client text {target}: not measured (no client here)")
            elif not tally.complete:
                out.append(f"client text {target}: {tally.translated} of {tally.total} strings translated")
    if glyphs_missing is None:
        out.append("glyphs: not measured")
    elif glyphs_missing:
        if isinstance(glyphs_missing, int):
            out.append(f"glyphs: the shipped UI fonts lack {glyphs_missing} characters the language needs")
        else:
            out.append(f"glyphs: the shipped UI fonts lack {len(glyphs_missing)} characters the language needs ({glyph_names(glyphs_missing)})")
    return out
