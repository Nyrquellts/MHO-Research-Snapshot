"""Synthetic checkout tests for static generator fingerprints."""

from pathlib import Path
import tempfile
import unittest

from mho.freshness import Code, Context, Rule


GEN = '''\
import argparse
import os

from mho import freshness, helper


def cmd_make(args):
    with open(args.out, "w") as f:
        f.write(helper.VALUE)


def cmd_other(args):
    return 2


def cmd_lazy(args):
    from mho import lazy
    return lazy.VALUE


def cmd_oracle(args):
    from mho import oracle
    return oracle.VALUE


def unrelated():
    return 1


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    one = sub.add_parser("make")
    one.add_argument("--out", default="build/a.json")
    two = sub.add_parser("other")
    two.add_argument("--x", default="1")
    args = p.parse_args(argv)
'''
MODULES = {
    "__init__.py": "",
    "helper.py": "from . import deeper\nVALUE = deeper.DEEP\n",
    "deeper.py": "DEEP = 'deep'\n",
    "lazy.py": "VALUE = 'lazy'\n",
    "oracle.py": "VALUE = 'oracle'\n",
    "freshness.py": "# the stamping: no part of what a generator makes\n",
}
GEN_PY = "scripts/gen.py"
MAKE = (GEN_PY, "make")


def code(*names, parser=None):
    return (Code(GEN_PY, tuple(names), parser=parser),)


class DigestTest(unittest.TestCase):
    rules = (
        Rule("a", ("build/a.json",), MAKE, code("cmd_make", parser="make")),
        Rule("c", ("build/c/*.json",), (GEN_PY, "other"), code("cmd_other", parser="other")),
        Rule("lazy", ("build/lazy.json",), (GEN_PY, "lazy"), code("cmd_lazy")),
        Rule("orc", ("build/orc.json",), (GEN_PY, "oracle"), code("cmd_oracle"), ignore=("oracle",)),
    )

    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = workspace.name
        self.write(GEN_PY, GEN)
        for name, text in MODULES.items():
            self.write(f"src/mho/{name}", text)

    def write(self, relative, text, crlf=False):
        path = Path(self.root) / relative
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(text, encoding="utf-8", newline="\r\n" if crlf else "\n")

    def edit(self, relative, old, new):
        text = (Path(self.root) / relative).read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, (relative, old))
        self.write(relative, text.replace(old, new))

    def digest(self, name):
        rule = next(rule for rule in self.rules if rule.name == name)
        return Context(self.root).generator(rule)

    def test_line_endings_do_not_change_it(self):
        before = self.digest("a")
        self.write(GEN_PY, GEN, crlf=True)
        for name, text in MODULES.items():
            self.write("src/mho/" + name, text, crlf=True)
        self.assertEqual(self.digest("a"), before)

    def test_a_real_edit_of_the_generators_function_changes_it(self):
        before = self.digest("a")
        self.edit(GEN_PY, 'f.write(helper.VALUE)', 'f.write(helper.VALUE + "!")')
        self.assertNotEqual(self.digest("a"), before)

    def test_another_command_of_the_same_script_does_not(self):
        before = self.digest("a")
        self.edit(GEN_PY, "    return 2\n", "    return 3\n")                  # cmd_other: no part of what `make` writes
        self.edit(GEN_PY, "def unrelated():\n    return 1\n", "def unrelated():\n    return 11\n")
        self.assertEqual(self.digest("a"), before)

    def test_the_commands_arguments_are_part_of_it(self):
        before, other = self.digest("a"), self.digest("c")
        self.edit(GEN_PY, 'default="build/a.json"', 'default="build/z.json"')
        self.assertNotEqual(self.digest("a"), before)
        self.assertEqual(self.digest("c"), other)                               # the other subcommand's block is not this one's
        self.edit(GEN_PY, 'default="1"', 'default="2"')
        self.assertNotEqual(self.digest("c"), other)

    def test_a_module_it_uses_changes_it_and_so_does_one_that_module_uses(self):
        before = self.digest("a")
        self.write("src/mho/helper.py", "from . import deeper\nVALUE = deeper.DEEP + 'x'\n")
        direct = self.digest("a")
        self.assertNotEqual(direct, before)
        self.write("src/mho/deeper.py", "DEEP = 'deeper'\n")
        self.assertNotEqual(self.digest("a"), direct)

    def test_a_module_imported_inside_the_function_counts(self):
        before = self.digest("lazy")
        self.write("src/mho/lazy.py", "VALUE = 'changed'\n")
        self.assertNotEqual(self.digest("lazy"), before)

    def test_a_module_the_rule_ignores_and_the_stamping_itself_do_not(self):
        before_orc, before_a = self.digest("orc"), self.digest("a")
        self.write("src/mho/oracle.py", "VALUE = 'research'\n")
        self.write("src/mho/freshness.py", "# a new way of stamping\n")
        self.assertEqual(self.digest("orc"), before_orc)
        self.assertEqual(self.digest("a"), before_a)

    def test_the_rule_itself_is_part_of_it(self):
        before = self.digest("a")
        changed = (Rule("a", ("build/a.json",), MAKE, code("cmd_make", parser="make"), version=2),) + self.rules[1:]
        self.assertNotEqual(Context(self.root).generator(changed[0]), before)


if __name__ == "__main__":
    unittest.main()
