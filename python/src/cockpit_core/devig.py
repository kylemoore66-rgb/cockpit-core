"""De-vig: turn a market's decimal odds into fair probabilities."""

import math
from collections.abc import Sequence

from cockpit_core.odds import Method, implied

CAP = 0.995
_TOL = 1e-12

__all__ = ["Method", "devig", "shin_from_implied"]


def _multiplicative(pi: list[float], total: float) -> list[float]:
    """Scale to total; cap at CAP and rescale the uncapped rest until stable."""
    capped: set[int] = set()
    while True:
        free = [i for i in range(len(pi)) if i not in capped]
        remaining = total - CAP * len(capped)
        if not free or remaining <= 0:
            raise ValueError("cannot normalise: every runner would be capped")
        scale = remaining / sum(pi[i] for i in free)
        newly = {i for i in free if pi[i] * scale > CAP}
        if not newly:
            return [CAP if i in capped else pi[i] * scale for i in range(len(pi))]
        capped |= newly


def _power(pi: list[float], total: float) -> list[float]:
    """Solve sum(pi_i ** k) = total for k by bisection on [0.01, 100]."""
    lo, hi = 0.01, 100.0

    def f(k: float) -> float:
        return sum(p**k for p in pi) - total

    if f(lo) < 0 or f(hi) > 0:  # f is decreasing in k
        raise ValueError("power de-vig: no root in k bracket [0.01, 100]")
    while hi - lo > _TOL:
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2
    return [p**k for p in pi]


def _shin(pi: list[float]) -> list[float]:
    """Shin (1993) insider-trading model: solve z by bisection on [0, 0.5)."""
    s = sum(pi)
    if s <= 1.0:
        return _multiplicative(pi, 1.0)

    def probs(z: float) -> list[float]:
        return [(math.sqrt(z * z + 4 * (1 - z) * p * p / s) - z) / (2 * (1 - z)) for p in pi]

    def f(z: float) -> float:
        return sum(probs(z)) - 1.0

    lo, hi = 0.0, 0.5
    if f(hi) > 0:
        raise ValueError("Shin de-vig: no root for z in [0, 0.5)")
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return probs((lo + hi) / 2)


def shin_from_implied(pi: Sequence[float]) -> list[float]:
    """Shin fair probabilities (summing to 1) from implied probabilities, each strictly in (0, 1).

    For a caller that has already rescaled implied probabilities, e.g. a partial book's priced runners
    divided by their fair total. Same model and fallback as devig(..., SHIN).
    """
    pi = list(pi)
    if not pi:
        raise ValueError("implied probabilities must not be empty")
    for p in pi:
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 < p < 1:
            raise ValueError(f"implied probabilities must be finite and in (0, 1), got {p!r}")
    return _shin([float(p) for p in pi])


def devig(odds: Sequence[float], method: Method, expected_total: float = 1.0) -> list[float]:
    """Fair probabilities for decimal odds, summing to expected_total, in input order."""
    if len(odds) == 0:
        raise ValueError("odds must not be empty")
    pi = [implied(o) for o in odds]
    if not 0 < expected_total < len(pi):
        raise ValueError(f"expected_total must be in (0, {len(pi)}), got {expected_total}")
    if method == Method.MULTIPLICATIVE:
        return _multiplicative(pi, expected_total)
    if method == Method.POWER:
        return _power(pi, expected_total)
    if method == Method.SHIN:
        if expected_total != 1:
            raise ValueError("Shin supports expected_total == 1 only")
        return _shin(pi)
    raise ValueError(f"unknown method {method!r}")
