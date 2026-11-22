"""Fingerprint an offline generator by the code and dependencies it uses."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from dataclasses import dataclass


VERSION = 1
IGNORED_MODULES = frozenset({"freshness"})


class FreshnessError(Exception):
    """A rule names code that is not there: the registry is wrong, not the data."""


@dataclass(frozen=True)
class Code:
    """Code that shapes an output: a script as a whole (``names`` empty), or only the top-level definitions of ``names`` and everything of the same
    script they use (unrelated commands are excluded).  ``parser`` names the subcommand whose ``add_parser``
    block in ``main()`` is part of it too (its default arguments shape the output).  ``ignore`` names definitions that the command never runs."""
    path: str
    names: tuple[str, ...] = ()
    parser: str | None = None
    ignore: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    """Select the code and metadata that affect a generator's outputs."""

    name: str
    outputs: tuple[str, ...]
    command: tuple[str, ...]
    code: tuple[Code, ...]
    modules: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    exact: bool = True
    bulk: bool = False
    ignore: tuple[str, ...] = ()
    version: int = 1


def norm(data: bytes) -> bytes:
    """Text without the difference between CRLF and LF."""
    return data.replace(b"\r\n", b"\n")


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for t in target.elts for n in _target_names(t)]
    return []


def mho_imports(tree: ast.AST | None, depth: int = 0) -> set[str]:
    """The ``mho`` modules (or names of ``mho``: the caller keeps the ones that are files) a piece of code imports, wherever in it the import sits.
    ``depth`` is how far below ``src/mho`` the file is (a relative import means a module of ``mho`` one level above a subpackage)."""
    out: set[str] = set()
    if tree is None:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            level = node.level - depth
            if node.level == 0:
                if node.module == "mho":
                    out.update(a.name for a in node.names)
                elif node.module and node.module.startswith("mho."):
                    out.add(node.module.split(".")[1])
            elif level == 1:
                if node.module:
                    out.add(node.module.split(".")[0])
                else:
                    out.update(a.name for a in node.names)
            elif level == 2 and node.module:
                out.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            out.update(a.name.split(".")[1] for a in node.names if a.name.startswith("mho."))
    return out


def _add_parser_name(stmt: ast.AST) -> str | None:
    """The subcommand a statement of ``main()`` adds (``sub.add_parser("example", ...)``), or None."""
    for node in ast.walk(stmt):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_parser" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            return node.args[0].value
    return None


def _parser_block(main: ast.FunctionDef, subcommand: str) -> list[ast.stmt]:
    """The statements of ``main()`` that define one subcommand's arguments: from its ``add_parser`` to the next subcommand's."""
    block: list[ast.stmt] = []
    inside = False
    for stmt in main.body:
        name = _add_parser_name(stmt)
        if name is not None:
            if inside:
                break
            inside = name == subcommand
        if inside:
            block.append(stmt)
    return block


def module_files(root: str, module: str) -> list[str]:
    """``src/mho/<module>.py``, or every file of the package ``src/mho/<module>/``; empty when ``mho`` has no such module."""
    one = f"src/mho/{module}.py"
    if os.path.isfile(os.path.join(root, *one.split("/"))):
        return [one]
    package = os.path.join(root, "src", "mho", module)
    if os.path.isdir(package):
        found = []
        for top, dirs, files in os.walk(package):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            found += [os.path.relpath(os.path.join(top, n), root).replace(os.sep, "/") for n in sorted(files) if n.endswith(".py")]
        return found
    return []


class Context:
    """One view of a local checkout. Create a new context to read later changes."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self._source_cache: dict[str, tuple[str | None, ast.AST | None]] = {}

    def path(self, rel: str) -> str:
        return os.path.join(self.root, *rel.split("/"))

    def _source(self, rel: str) -> tuple[str | None, ast.AST | None]:
        if rel not in self._source_cache:
            try:
                with open(self.path(rel), "rb") as f:
                    text = norm(f.read()).decode("utf-8", errors="replace")
            except OSError:
                self._source_cache[rel] = (None, None)
            else:
                try:
                    tree: ast.AST | None = ast.parse(text)
                except (SyntaxError, ValueError):
                    tree = None
                self._source_cache[rel] = (text, tree)
        return self._source_cache[rel]

    def _code(self, code: Code, ignore: set[str]) -> tuple[dict[str, str], set[str]]:
        text, tree = self._source(code.path)
        if text is None:
            raise FreshnessError(f"{code.path}: the generator's code is not there")
        if not code.names:
            return {code.path: text}, mho_imports(tree)
        if tree is None:
            raise FreshnessError(f"{code.path}: cannot be parsed")
        lines = text.split("\n")
        defs: dict[str, list[ast.stmt]] = {}
        bound: dict[str, str] = {}          # a name the script imports from mho -> the module
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs.setdefault(node.name, []).append(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for name in _target_names(target):
                        defs.setdefault(name, []).append(node)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and (node.module == "mho" or node.module.startswith("mho.")):
                for alias in node.names:
                    bound[alias.asname or alias.name] = alias.name if node.module == "mho" else node.module.split(".")[1]
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("mho."):
                        bound[alias.asname or alias.name.split(".")[0]] = alias.name.split(".")[1]

        def span(nodes: list[ast.stmt]) -> str:
            first = min(min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])]) for n in nodes)
            return "\n".join(lines[first - 1:max(n.end_lineno for n in nodes)])

        segments: dict[str, str] = {}
        modules: set[str] = set()
        work: list[str] = []
        for name in code.names:
            if name not in defs:
                raise FreshnessError(f"{code.path} has no top-level definition {name!r}")
            work.append(name)
        if code.parser:
            main = next((n for n in defs.get("main", []) if isinstance(n, ast.FunctionDef)), None)
            block = _parser_block(main, code.parser) if main is not None else []
            if not block:
                raise FreshnessError(f"{code.path}: main() has no add_parser({code.parser!r}) block")
            segments[f"{code.path}:main[{code.parser}]"] = span(block)
            holder = ast.Module(body=block, type_ignores=[])
            modules |= mho_imports(holder)
            for sub in ast.walk(holder):
                if isinstance(sub, ast.Name):
                    if sub.id in defs:
                        work.append(sub.id)
                    elif sub.id in bound:
                        modules.add(bound[sub.id])
        ignored = set(code.ignore) | ignore
        seen: set[str] = set()
        while work:
            name = work.pop()
            if name in seen or name in ignored:
                continue
            seen.add(name)
            nodes = defs[name]
            segments[f"{code.path}:{name}"] = span(nodes)
            for node in nodes:
                modules |= mho_imports(node)
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Name):
                        if sub.id in defs and sub.id not in seen:
                            work.append(sub.id)
                        elif sub.id in bound:
                            modules.add(bound[sub.id])
        return segments, modules

    def parts(self, rule: Rule) -> dict[str, str]:
        """``{label: text}`` of everything the generator's digest is made of."""
        ignore = set(rule.ignore) | IGNORED_MODULES
        parts: dict[str, str] = {"rule": json.dumps([VERSION, rule.name, rule.version, list(rule.command), list(rule.outputs), list(rule.needs),
                                                     list(rule.sources), [], rule.exact, rule.bulk])}
        modules = set(rule.modules)
        for code in rule.code:
            segments, mods = self._code(code, ignore)
            parts.update(segments)
            modules |= mods
        seen: set[str] = set()
        work = sorted(modules)
        while work:
            module = work.pop()
            if module in seen or module in ignore:
                continue
            seen.add(module)
            for rel in module_files(self.root, module):
                text, tree = self._source(rel)
                parts[rel] = text or ""
                work.extend(mho_imports(tree, rel.count("/") - 2))
        return parts

    def generator(self, rule: Rule) -> str:
        """Hash the selected definitions and dependencies without importing or running them."""
        digest = hashlib.sha256()
        for label, text in sorted(self.parts(rule).items()):
            digest.update(label.encode("utf-8") + b"\0" + hashlib.sha256(text.encode("utf-8")).digest())
        return digest.hexdigest()
