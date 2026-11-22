"""Exercise build fingerprints and stamp reports with synthetic files and Git history."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from mho import buildstamp as bs


SHA = "80e64adc0ffee11223344556677889900aabbccd"


SOURCE = "0123456789abcdef" * 4


DATA = "fedcba9876543210" * 4


BUILT = "2026-10-04T06:12:33Z"


LINE = "build stamp: 80e64adc0ffe clean built 2026-10-04T06:12:33Z source 0123456789ab data fedcba987654"


def stamp(**kw):
    out = bs.make(".", SOURCE, DATA, BUILT, sha=SHA, is_dirty=False)
    out.update(kw)
    return out


def now(**kw):
    out = {"sha": SHA, "dirty": False, "source": SOURCE, "data": DATA}
    out.update(kw)
    return out


class TheFileAndTheLineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_formats_a_clean_or_dirty_stamp(self):
        self.assertEqual(bs.server_line(stamp()), LINE)
        self.assertEqual(bs.server_line(stamp(dirty=True)), LINE.replace(" clean ", " dirty "))

    def test_roundtrip_preserves_the_stamp_fields(self):
        path = bs.write(self.dir.name, stamp())
        self.assertEqual(os.path.basename(path), "build_stamp.json")
        self.assertEqual(bs.read(self.dir.name), stamp())
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(set(doc), {"sha", "dirty", "built", "source", "data", "deploy"})
        self.assertIs(doc["dirty"], False)
        self.assertEqual(doc["deploy"], bs.combine(SOURCE, DATA))

    def test_a_folder_without_a_stamp_or_with_a_damaged_one_has_none(self):
        self.assertIsNone(bs.read(self.dir.name))
        path = os.path.join(self.dir.name, bs.STAMP_FILE)
        for text in ("", "{", "[]", '{"sha": "a"}', json.dumps(dict(stamp(), dirty="no")), json.dumps(dict(stamp(), source=""))):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.assertIsNone(bs.read(self.dir.name), text)

    def test_the_line_is_read_back_from_a_log_and_the_last_one_counts(self):
        log = f"2026-10-04 06:13:01 Info Server: first\n2026-10-04 06:13:02 Info {bs.server_line(stamp(sha='1' * 40))}\n2026-10-04 06:13:03 Info {LINE}\nlater line\n"
        found = bs.parse_line(log)
        self.assertEqual(found, {"sha": "80e64adc0ffe", "dirty": False, "built": BUILT, "source": SOURCE[:12], "data": DATA[:12]})
        self.assertIsNone(bs.parse_line("build stamp: none (build_stamp.json is not beside this server)"))
        self.assertIsNone(bs.parse_line(""))
        self.assertTrue(bs.parse_line(LINE.replace(" clean ", " dirty "))["dirty"])

    def test_a_shortened_stamp_is_the_same_build_as_the_full_one(self):
        self.assertTrue(bs.same_build(bs.parse_line(LINE), stamp()))
        self.assertFalse(bs.same_build(bs.parse_line(LINE), stamp(sha="1" * 40)))
        self.assertFalse(bs.same_build(bs.parse_line(LINE), stamp(source="1" * 64)))
        self.assertFalse(bs.same_build(bs.parse_line(LINE), stamp(data="1" * 64)))
        self.assertFalse(bs.same_build(bs.parse_line(LINE), stamp(dirty=True)))
        self.assertFalse(bs.same_build({}, stamp()))

    def test_fingerprint_changes_with_source_or_data(self):
        self.assertEqual(bs.combine(SOURCE, DATA), bs.combine(SOURCE, DATA))
        self.assertNotEqual(bs.combine(SOURCE, DATA), bs.combine(DATA, SOURCE))
        self.assertNotEqual(bs.combine(SOURCE, DATA), bs.combine(SOURCE, "0" * 64))


class TheSourceDigestTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = self.dir.name
        self.put("Service/Server.cs", "class Server {}")
        self.put("Service/Data.json", "{}")

    def put(self, name, text):
        path = os.path.join(self.root, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def test_a_changed_file_is_another_digest_and_build_output_tests_and_notes_are_not_part_of_it(self):
        before = bs.source_fingerprint(self.root)
        self.assertEqual(before, bs.source_fingerprint(self.root))
        self.put("Service/bin/Debug/artifact.bin", "x")
        self.put("Service/obj/x.cache", "x")
        self.put("Service.Test/ServerTest.cs", "class T {}")
        self.put("NOTES.md", "notes")
        self.assertEqual(bs.source_fingerprint(self.root), before)
        self.put("Service/Server.cs", "class Server { int x; }")
        self.assertNotEqual(bs.source_fingerprint(self.root), before)


class TheVerdictTest(unittest.TestCase):
    """Compare matching, missing, older, and different build stamps."""

    def verdict(self, live, current=None, behind=None):
        return bs.verdict(live, current or now(), ".", behind=lambda root, sha: behind)

    def test_the_build_of_this_commit_is_this_checkout(self):
        out = self.verdict(stamp(), behind=0)
        self.assertEqual((out["kind"], out["ok"], out["behind"]), ("same", True, 0))
        self.assertEqual(out["text"], "build: 80e64adc0ffe 2026-10-04 06:12 UTC (= this checkout)")

    def test_later_commits_that_change_nothing_the_server_ships_leave_it_current(self):
        out = self.verdict(stamp(), current=now(sha="2" * 40), behind=3)
        self.assertEqual((out["kind"], out["ok"], out["behind"]), ("same", True, 3))
        self.assertIn("(= this checkout; 3 later commits change nothing it ships)", out["text"])

    def test_compares_source_and_data_of_an_older_build(self):
        out = self.verdict(stamp(), current=now(sha="2" * 40, source="9" * 64), behind=2)
        self.assertEqual((out["kind"], out["ok"], out["behind"], out["differs"]), ("behind", False, 2, ["server source"]))
        self.assertEqual(out["text"], "build: 80e64adc0ffe 2026-10-04 06:12 UTC (2 commits behind; its server source differs from this checkout's)")
        out = self.verdict(stamp(), current=now(sha="2" * 40, data="9" * 64), behind=1)
        self.assertEqual((out["kind"], out["ok"], out["differs"]), ("behind", False, ["data stamp"]))
        self.assertIn("(1 commit behind; its data stamp differs from this checkout's)", out["text"])
        out = self.verdict(stamp(), current=now(source="9" * 64, data="8" * 64), behind=0)
        self.assertEqual((out["kind"], out["ok"], out["differs"]), ("different", False, ["server source", "data stamp"]))
        self.assertIn("its server source and data stamp differ from this checkout's", out["text"])

    def test_unrelated_history_is_reported_as_different(self):
        out = self.verdict(stamp(), current=now(sha="2" * 40, data="9" * 64), behind=None)
        self.assertEqual((out["kind"], out["ok"], out["behind"]), ("different", False, None))
        self.assertNotIn("behind", out["text"])

    def test_identifies_matching_content_from_a_dirty_tree(self):
        out = self.verdict(stamp(dirty=True), behind=0)
        self.assertEqual((out["kind"], out["ok"]), ("dirty", True))
        self.assertIn("built from a dirty tree", out["text"])
        out = self.verdict(stamp(dirty=True), current=now(source="9" * 64), behind=0)
        self.assertEqual((out["kind"], out["ok"]), ("different", False))
        self.assertIn("built from a dirty tree", out["text"])

    def test_missing_stamp_is_reported(self):
        out = self.verdict(None)
        self.assertEqual((out["kind"], out["ok"], out["differs"]), ("none", False, ["no stamp"]))
        self.assertTrue(out["text"].startswith("build: no stamp"), out["text"])

    def test_a_commit_the_stamp_could_not_name_is_judged_by_content_alone(self):
        out = self.verdict(stamp(sha="unknown"), behind=5)
        self.assertEqual((out["kind"], out["ok"]), ("same", True))
        out = self.verdict(stamp(sha="unknown"), current=now(source="9" * 64), behind=5)
        self.assertEqual((out["kind"], out["ok"], out["behind"]), ("different", False, None))


@unittest.skipUnless(shutil.which("git"), "git is needed for the repository questions")
class TheRepositoryQuestionsTest(unittest.TestCase):
    """The three things asked of git, against a real repository in a temporary folder."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = self.dir.name
        self.git("init", "-q")
        os.makedirs(os.path.join(self.root, "server"))
        self.put("server/a.cs", "a")
        self.put("note.txt", "n")
        self.commit("first")
        self.first = bs.head(self.root)

    def git(self, *args):
        subprocess.run(["git", "-C", self.root, "-c", "user.name=t", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=.git/no-hooks", *args],
                       check=True, capture_output=True, stdin=subprocess.DEVNULL)

    def put(self, name, text):
        with open(os.path.join(self.root, *name.split("/")), "w", encoding="utf-8") as f:
            f.write(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def test_the_head_is_a_full_commit_id_and_a_clean_tree_is_not_dirty(self):
        self.assertRegex(self.first, r"^[0-9a-f]{40}$")
        self.assertFalse(bs.dirty(self.root))

    def test_a_changed_tracked_file_or_a_new_server_file_is_dirty_and_a_new_note_is_not(self):
        self.put("note.txt", "changed")
        self.assertTrue(bs.dirty(self.root))
        self.put("note.txt", "n")
        self.assertFalse(bs.dirty(self.root))
        self.put("scratch.log", "x")                                 # untracked outside server/: not part of any build
        self.assertFalse(bs.dirty(self.root))
        self.put("server/new.cs", "b")                               # untracked under server/: part of a build
        self.assertTrue(bs.dirty(self.root))

    def test_commits_behind_counts_what_the_checkout_has_that_the_build_lacks(self):
        self.assertEqual(bs.commits_behind(self.root, self.first), 0)
        self.put("note.txt", "2")
        self.commit("second")
        self.put("note.txt", "3")
        self.commit("third")
        self.assertEqual(bs.commits_behind(self.root, self.first), 2)
        self.assertIsNone(bs.commits_behind(self.root, "1" * 40))     # not a commit of this history
        self.assertIsNone(bs.commits_behind(self.root, ""))

    def test_a_folder_that_is_no_repository_is_unknown_not_an_error(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertIsNone(bs.head(plain))
            self.assertIsNone(bs.dirty(plain))
            self.assertIsNone(bs.commits_behind(plain, self.first))
            self.assertEqual(bs.make(plain, SOURCE, DATA, BUILT)["sha"], "unknown")


if __name__ == "__main__":
    unittest.main()
