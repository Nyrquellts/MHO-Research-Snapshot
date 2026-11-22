"""Profile parsing for the baseline and fixed-step simulation experiments.

A profile selects independent behavior switches. Simulation and movement update
rates can be inspected separately, using a supplied environment or profile file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

VARIABLE = "MHO_RUNTIME_PROFILE"
FILE_NAME = "runtime_profile.txt"
LEGACY = "legacy165"
REPAIR = "repair60"
SUBSYSTEMS = ("clock", "movement_sync", "reactions", "hitfly", "hp_ui", "world_movement", "input_hold", "parts", "attacks", "aim", "damage", "region_walk", "gauge", "faction", "flight")
REPAIR_HZ = 60.0        # RuntimeProfile.Repair60Hz: the simulation's fixed step rate under repair60.clock (a count, not a measurement)
LEGACY_HZ = 165.0       # StepRate.DefaultHz: the baseline's drive, which MHO_DRIVE_HZ may move within DRIVE_HZ_RANGE
DRIVE_HZ_RANGE = (30.0, 360.0)
DRIVE_VARIABLE = "MHO_DRIVE_HZ"
SYNC_VARIABLE = "MHO_MONSTER_SYNC_HZ"
SYNC_HZ = 30.0          # Movement update cadence when its separate clock is enabled
SYNC_HZ_RANGE = (10.0, 120.0)


@dataclass(frozen=True)
class Profile:
    """One parsed line of the grammar. ``unknown`` holds the words that name nothing: the line was invalid and the profile is the baseline because of them."""

    name: str
    on: frozenset
    unknown: tuple = ()

    @property
    def is_repair60(self) -> bool:
        return self.name == REPAIR

    def has(self, subsystem: str) -> bool:
        return subsystem in self.on

    @property
    def clock(self) -> bool:
        """``RuntimeProfile.Clock``: the fixed 60 Hz simulation step (commit 2)."""
        return "clock" in self.on

    @property
    def movement_sync(self) -> bool:
        """Whether movement uses a cadence separate from the simulation step."""
        return "movement_sync" in self.on

    @property
    def on_in_order(self) -> tuple:
        return tuple(s for s in SUBSYSTEMS if s in self.on)

    def __str__(self) -> str:
        """``RuntimeProfile.ToString``: the shortest line that names this profile."""
        if not self.is_repair60:
            return LEGACY
        if len(self.on) == len(SUBSYSTEMS):
            return REPAIR
        if not self.on:
            return REPAIR + " " + " ".join("-" + s for s in SUBSYSTEMS)
        return " ".join(REPAIR + "." + s for s in self.on_in_order)


LEGACY_PROFILE = Profile(LEGACY, frozenset())
REPAIR_PROFILE = Profile(REPAIR, frozenset(SUBSYSTEMS))


def words_of(text: str) -> list:
    """The words of a line as ``RuntimeProfile.Parse`` splits them: on spaces, tabs, commas and semicolons, lower-cased, empties dropped."""
    return [w.lower() for w in text.replace(",", " ").replace(";", " ").replace("\t", " ").split(" ") if w]


def parse(text: str | None) -> Profile:
    """``RuntimeProfile.Parse``: None or blank is the baseline; ``legacy165`` alone; ``repair60`` (all on) or ``repair60.<sub>`` first, then ``repair60.<sub>``
    to add and ``-<sub>`` to remove; any other word makes the line invalid -- the baseline, with the words in ``unknown``."""
    if text is None or not text.strip():
        return LEGACY_PROFILE
    words = words_of(text.strip())
    if not words:
        return Profile(LEGACY, frozenset(), (text.strip(),))      # separators only: a line that names nothing is invalid (RuntimeProfile.Parse says the same)
    unknown: list = []
    on: set = set()
    dotted = REPAIR + "."
    first = words[0]

    def add(sub: str) -> bool:
        if sub not in SUBSYSTEMS:
            return False
        on.add(sub)
        return True

    if first == LEGACY:
        name = LEGACY
        unknown.extend(words[1:])
    elif first == REPAIR or first.startswith(dotted):
        name = REPAIR
        if first == REPAIR:
            on.update(SUBSYSTEMS)
        elif not add(first[len(dotted):]):
            unknown.append(first)
        for word in words[1:]:
            if word.startswith(dotted):
                if not add(word[len(dotted):]):
                    unknown.append(word)
            elif len(word) > 1 and word[0] == "-":
                sub = word[1:]
                if sub in SUBSYSTEMS:
                    on.discard(sub)
                else:
                    unknown.append(word)
            else:
                unknown.append(word)
    else:
        name = LEGACY
        unknown.extend(words)
    if unknown:
        return Profile(LEGACY, frozenset(), tuple(unknown))
    return Profile(name, frozenset(on))


def valid(line: str) -> bool:
    """Whether the server would play the line as written (a blank line names nothing and is not a profile line)."""
    return bool(line and line.strip()) and not parse(line).unknown


def first_line(path: str) -> str | None:
    """The first line of the file that is not blank and not a ``#`` comment, stripped; None when there is none or no file."""
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        return None
    return None


def load(environ: Mapping[str, str] | None = None, files_dir: str | None = None) -> Profile:
    """``RuntimeProfile.Load``: the variable if it says anything, else the first profile line of ``<files_dir>/runtime_profile.txt`` when a folder is given, else
    the baseline. An invalid line is the baseline with its ``unknown`` words (the server logs them and plays legacy165)."""
    env = os.environ if environ is None else environ
    text = env.get(VARIABLE, "")
    if not text.strip() and files_dir:
        text = first_line(os.path.join(files_dir, FILE_NAME)) or ""
    return parse(text)


def current(environ: Mapping[str, str] | None = None) -> Profile:
    """The profile this process's environment names (the variable only)."""
    return load(environ)


def drive_hz(environ: Mapping[str, str] | None = None, default: float = LEGACY_HZ, files_dir: str | None = None) -> float:
    """The step rate of the server's monster drive for a server started with this environment (and, when given, this ``Files`` folder): ``REPAIR_HZ`` when the
    profile's clock is on -- fixed, ``MHO_DRIVE_HZ`` cannot move it -- else ``MHO_DRIVE_HZ`` when it is a number within ``DRIVE_HZ_RANGE``, else ``default``."""
    env = os.environ if environ is None else environ
    if load(env, files_dir).clock:
        return REPAIR_HZ
    try:
        hz = float(env.get(DRIVE_VARIABLE, ""))
    except ValueError:
        hz = 0.0
    low, high = DRIVE_HZ_RANGE
    return hz if low <= hz <= high else default


def sync_hz(environ: Mapping[str, str] | None = None, default: float = SYNC_HZ) -> float:
    """The replication clock of a server started with this environment (``ReplicationPolicy.ReadHz``): ``MHO_MONSTER_SYNC_HZ`` when it is a number within
    ``SYNC_HZ_RANGE``, else ``default``. Read whatever the profile; the baseline does not place at it (``placement_hz``)."""
    env = os.environ if environ is None else environ
    try:
        hz = float(env.get(SYNC_VARIABLE, ""))
    except ValueError:
        hz = 0.0
    low, high = SYNC_HZ_RANGE
    return hz if low <= hz <= high else default


def placement_hz(environ: Mapping[str, str] | None = None, default: float = LEGACY_HZ, files_dir: str | None = None) -> float:
    """Return the movement update cadence for the effective profile."""
    env = os.environ if environ is None else environ
    if load(env, files_dir).movement_sync:
        return sync_hz(env)
    return drive_hz(env, default, files_dir)
