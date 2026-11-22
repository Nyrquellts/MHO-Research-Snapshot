"""Status buildup with configurable thresholds, tolerance, and effects."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ailment:
    name: str
    threshold: float          # initial build-up needed to proc
    tol_add: float            # threshold increase per proc (tolerance)
    tol_max: float            # threshold cap
    dmg_per_tick: float       # poison only (else 0)
    ticks: int                # poison only
    duration: float           # immobilise/sleep seconds (paralysis/sleep)


@dataclass
class ProcEffect:
    ailment: str
    kind: str                 # 'dot' | 'immobilize' | 'sleep'
    dmg_per_tick: float = 0.0
    ticks: int = 0
    duration: float = 0.0


class StatusTracker:
    """Accumulates ailment build-up on a monster and procs effects at threshold.

    On a proc the current threshold rises by ``tol_add`` (up to ``tol_max``) and build-up
    resets.
    """

    def __init__(self, ailments: dict[str, Ailment]):
        self.ailments = ailments
        self._buildup: dict[str, float] = {k: 0.0 for k in ailments}
        self._threshold: dict[str, float] = {k: a.threshold for k, a in ailments.items()}

    def apply(self, ailment: str, amount: float) -> ProcEffect | None:
        a = self.ailments.get(ailment)
        if a is None or amount <= 0:
            return None
        self._buildup[ailment] += amount
        if self._buildup[ailment] < self._threshold[ailment]:
            return None
        # proc
        self._buildup[ailment] = 0.0
        self._threshold[ailment] = min(a.tol_max, self._threshold[ailment] + a.tol_add)
        if ailment == "poison":
            return ProcEffect("poison", "dot", a.dmg_per_tick, a.ticks)
        if ailment == "sleep":
            return ProcEffect("sleep", "sleep", duration=a.duration)
        return ProcEffect(ailment, "immobilize", duration=a.duration)

    def threshold(self, ailment: str) -> float:
        return self._threshold.get(ailment, 0.0)
