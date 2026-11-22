"""Local build fingerprints, provenance stamps, and comparison reports."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from typing import Callable, Optional


STAMP_FILE = "build_stamp.json"
LINE_PREFIX = "build stamp: "
SOURCE_SKIP = ("bin", "obj", ".vs", "TestResults")
_LINE = re.compile(r"build stamp: (?P<sha>[0-9a-f]{4,40}) (?P<tree>clean|dirty) built (?P<built>\S+) source (?P<source>[0-9a-f]{4,64}) data (?P<data>[0-9a-f]{4,64})")
SHORT = 12


def source_fingerprint(server_root: str) -> str:
    """Hash selected source files by relative path and content, excluding tests, notes, and build output."""
    digest = hashlib.sha256()
    for top, dirs, files in os.walk(server_root):
        dirs[:] = sorted(d for d in dirs if d not in SOURCE_SKIP and not d.endswith((".Test", ".Tests")))
        for name in sorted(files):
            if name.lower().endswith(".md"):
                continue
            path = os.path.join(top, name)
            with open(path, "rb") as f:
                content = hashlib.sha256(f.read()).digest()
            digest.update(os.path.relpath(path, server_root).replace(os.sep, "/").encode("utf-8") + b"\0" + content)
    return digest.hexdigest()


def combine(source: str, data: str) -> str:
    """Combine the source and data digests into a single build fingerprint."""
    digest = hashlib.sha256()
    digest.update(source.encode() + b"\0" + data.encode())
    return digest.hexdigest()


def _git(root: str, *args: str, timeout: float = 30.0) -> Optional[str]:
    """The output of a git command run in ``root``, stripped; None when git is missing, the command fails or the folder is no repository."""
    try:
        done = subprocess.run(
            ["git", "--no-optional-locks", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def head(root: str) -> Optional[str]:
    sha = _git(root, "rev-parse", "HEAD")
    return sha if sha and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def dirty(root: str) -> Optional[bool]:
    """Check tracked changes and untracked files under server/. Return None when Git cannot answer."""
    changed = _git(root, "status", "--porcelain", "--untracked-files=no")
    if changed is None:
        return None
    if changed:
        return True
    new = _git(root, "ls-files", "--others", "--exclude-standard", "--", "server")
    return bool(new) if new is not None else None


def commits_behind(root: str, sha: str) -> Optional[int]:
    """How many commits the checkout's HEAD has that ``sha`` has not (0 when ``sha`` is HEAD); None when ``sha`` is not an ancestor of HEAD or unknown to git."""
    if not re.fullmatch(r"[0-9a-f]{4,40}", sha) or _git(root, "merge-base", "--is-ancestor", sha, "HEAD") is None:
        return None
    count = _git(root, "rev-list", "--count", f"{sha}..HEAD")
    return int(count) if count and count.isdigit() else None


def utc(t: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if t is None else t))


def make(root: str, source: str, data: str, built: Optional[str] = None, *, sha: Optional[str] = None, is_dirty: Optional[bool] = None) -> dict:
    """Make a provenance stamp with the commit, tree state, build time, and content digests."""
    return {"sha": sha if sha is not None else (head(root) or "unknown"), "dirty": bool(dirty(root) if is_dirty is None else is_dirty),
            "built": built or utc(), "source": source, "data": data, "deploy": combine(source, data)}


def write(folder: str, stamp: dict) -> str:
    path = os.path.join(folder, STAMP_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stamp, f, indent=1, sort_keys=True)
        f.write("\n")
    return path


def read(folder: str) -> Optional[dict]:
    """Read a build stamp from a folder. Return None for missing or invalid stamps."""
    try:
        with open(os.path.join(folder, STAMP_FILE), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if valid_stamp(doc) else None


def valid_stamp(doc) -> bool:
    """Whether ``doc`` is a stamp: the commit, the build time and the two digests as text, the tree's state as a flag."""
    return (isinstance(doc, dict) and all(isinstance(doc.get(k), str) and doc.get(k) for k in ("sha", "built", "source", "data"))
            and isinstance(doc.get("dirty"), bool))


def server_line(stamp: dict) -> str:
    """Format a compact build-stamp line for diagnostics."""
    return (f"{LINE_PREFIX}{stamp['sha'][:SHORT]} {'dirty' if stamp['dirty'] else 'clean'} built {stamp['built']} "
            f"source {stamp['source'][:SHORT]} data {stamp['data'][:SHORT]}")


def parse_line(text: str) -> Optional[dict]:
    """Read the last compact build-stamp line within text."""
    found = None
    for m in _LINE.finditer(text or ""):
        found = {"sha": m.group("sha"), "dirty": m.group("tree") == "dirty", "built": m.group("built"), "source": m.group("source"), "data": m.group("data")}
    return found


def _same_text(x, y) -> bool:
    """Compare a commit or digest with a potentially shortened form."""
    x, y = str(x or ""), str(y or "")
    n = min(len(x), len(y))
    return bool(n) and x[:n] == y[:n]


def same_build(a: dict, b: dict) -> bool:
    """Compare the commit, tree state, and diagnostic prefixes of both content digests."""
    for key in ("sha", "source", "data"):
        x, y = str(a.get(key, "")), str(b.get(key, ""))
        n = min(len(x), len(y), SHORT)
        if not n or x[:n] != y[:n]:
            return False
    return bool(a.get("dirty")) == bool(b.get("dirty"))


def checkout(root: str, server_root: str, data: Callable[[], str]) -> dict:
    """Collect the local checkout commit, tree state, and content digests."""
    return {"sha": head(root) or "unknown", "dirty": bool(dirty(root)), "source": source_fingerprint(server_root), "data": data()}


def _when(built: str) -> str:
    m = re.match(r"(\d{4}-\d\d-\d\d)T(\d\d:\d\d)", built)
    return f"{m.group(1)} {m.group(2)} UTC" if m else built


def verdict(live: Optional[dict], now: dict, root: str, behind: Callable[[str, str], Optional[int]] = commits_behind, label: str = "build") -> dict:
    """Report whether the supplied build stamp matches the checkout's source and data."""
    if live is None:
        return {"kind": "none", "ok": False, "behind": None, "differs": ["no stamp"],
                "text": f"{label}: no stamp found"}
    differs = [name for name, key in (("server source", "source"), ("data stamp", "data")) if not _same_text(live.get(key), now.get(key))]
    n = behind(root, live["sha"]) if live["sha"] != "unknown" else None
    short = live["sha"][:SHORT]
    head_line = f"{label}: {short} {_when(live['built'])}"
    notes = []
    if live["dirty"]:
        notes.append("built from a dirty tree")
    if differs:
        if n:
            notes.insert(0, f"{n} commit{'s' if n != 1 else ''} behind")
        notes.append("its " + " and ".join(differs) + (" differs" if len(differs) == 1 else " differ") + " from this checkout's")
        kind = "behind" if n else "different"
        return {"kind": kind, "ok": False, "behind": n, "differs": differs, "text": f"{head_line} ({'; '.join(notes)})"}
    if _same_text(live["sha"], now.get("sha")) and not live["dirty"]:
        return {"kind": "same", "ok": True, "behind": 0, "differs": [], "text": f"{head_line} (= this checkout)"}
    if live["dirty"]:
        notes.append("its source and data are this checkout's")
        return {"kind": "dirty", "ok": True, "behind": n, "differs": [], "text": f"{head_line} ({'; '.join(notes)})"}
    later = f"; {n} later commit{'s' if n != 1 else ''} change nothing it ships" if n else ""
    return {"kind": "same", "ok": True, "behind": n, "differs": [], "text": f"{head_line} (= this checkout{later})"}
