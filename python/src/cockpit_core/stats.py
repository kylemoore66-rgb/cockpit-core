"""Inference and scoring: CLV, clustered bootstrap, Holm, proper scoring rules."""

import math
from collections.abc import Collection, Hashable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from cockpit_core.clv import clv

B_DEFAULT = 5000
SEED_DEFAULT = 20261020
_P_MIN = 1e-9
_CHUNK_ELEMENTS = 2_000_000


@dataclass(frozen=True)
class Estimate:
    """A bet-weighted mean with a cluster-bootstrap CI and one-sided p-value."""

    n: int  # bets
    n_events: int  # distinct clusters
    mean: float  # observed bet-weighted mean of the full sample
    lo: float
    hi: float
    p_one_sided: float  # (1 + #(boot <= 0)) / (B + 1)

    def __post_init__(self) -> None:
        if not self.n >= 1:
            raise ValueError(f"n must be >= 1, got {self.n}")
        if not 0 <= self.n_events <= self.n:
            raise ValueError(f"n_events must be in [0, n={self.n}], got {self.n_events}")
        for name in ("mean", "lo", "hi"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite, got {getattr(self, name)}")
        if not self.lo <= self.hi:
            raise ValueError(f"lo ({self.lo}) must not exceed hi ({self.hi})")
        if not 0.0 < self.p_one_sided <= 1.0:
            raise ValueError(f"p_one_sided must be in (0, 1], got {self.p_one_sided}")


def _as_float_array(x: Any, name: str) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1-D")
    return arr


def _factorise(clusters: Any) -> tuple[np.ndarray, int]:
    """Map cluster labels (scalars or row tuples) to codes 0..K-1 in sorted label order.

    Sorted order makes the code assignment independent of row order. Labels that
    cannot be sorted together fall back to order of first appearance.
    """
    if isinstance(clusters, np.ndarray) and clusters.ndim == 1 and clusters.dtype != object:
        uniq, codes = np.unique(clusters, return_inverse=True)
        return codes.ravel().astype(np.int64), len(uniq)
    labels: list[Hashable] = [
        tuple(c) if isinstance(c, (tuple, list, np.ndarray)) else c for c in clusters
    ]
    try:
        order = sorted(set(labels))  # type: ignore[type-var]
    except TypeError:
        order = list(dict.fromkeys(labels))
    index = {label: i for i, label in enumerate(order)}
    codes = np.fromiter((index[label] for label in labels), dtype=np.int64, count=len(labels))
    return codes, len(order)


def cluster_bootstrap(
    values: np.ndarray,
    clusters: Any,
    *,
    b: int = B_DEFAULT,
    seed: int = SEED_DEFAULT,
    alpha: float = 0.05,
) -> Estimate:
    """Bootstrap the bet-weighted mean by resampling whole clusters (events).

    Each of `b` replicates draws K clusters with replacement (K = distinct clusters),
    pools all their bets and takes sum(values) / count(bets). The CI is the percentile
    interval (np.percentile, linear interpolation) at alpha/2 and 1 - alpha/2.
    p_one_sided = (1 + #(replicate <= 0)) / (b + 1). `clusters` is a 1-D array of
    labels or a 2-D array / list of tuples such as (year, canonical_event).

    The result does not depend on input row order: rows are sorted by (cluster, value)
    before the per-cluster sums, and the observed mean is an exactly rounded fsum.
    """
    v = _as_float_array(values, "values")
    if v.size < 1:
        raise ValueError("need at least one bet")
    if not np.all(np.isfinite(v)):
        raise ValueError("values must be finite")
    if b < 1:
        raise ValueError(f"b must be >= 1, got {b}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    codes, k = _factorise(clusters)
    if len(codes) != v.size:
        raise ValueError(f"values ({v.size}) and clusters ({len(codes)}) differ in length")

    order = np.lexsort((v, codes))
    codes, v = codes[order], v[order]
    sums = np.bincount(codes, weights=v, minlength=k)
    counts = np.bincount(codes, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    boot = np.empty(b)
    rows = max(1, _CHUNK_ELEMENTS // k)
    for start in range(0, b, rows):
        stop = min(start + rows, b)
        idx = rng.integers(0, k, size=(stop - start, k))
        boot[start:stop] = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)

    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return Estimate(
        n=int(v.size),
        n_events=int(k),
        mean=math.fsum(v.tolist()) / v.size,
        lo=float(lo),
        hi=float(hi),
        p_one_sided=float((1 + np.count_nonzero(boot <= 0.0)) / (b + 1)),
    )


def paired_cluster_bootstrap(a: np.ndarray, b_: np.ndarray, clusters: Any, **kw: Any) -> Estimate:
    """Cluster bootstrap of mean(a - b_) using the same cluster resampling."""
    av, bv = _as_float_array(a, "a"), _as_float_array(b_, "b_")
    if av.size != bv.size:
        raise ValueError(f"a ({av.size}) and b_ ({bv.size}) differ in length")
    return cluster_bootstrap(av - bv, clusters, **kw)


def holm(
    pvalues: Mapping[str, float], alpha: float = 0.05, *, family: Collection[str] | None = None
) -> dict[str, bool]:
    """Holm step-down: reject the i-th smallest p while p <= alpha / (m - i); stop at first failure.

    `family` is the pre-registered candidate list; when given, the p-values must cover it
    exactly, so the family cannot shrink. Pass a candidate with no holdout estimate as p = 1.0.
    """
    if isinstance(family, (str, bytes, bytearray)):
        raise TypeError("family must be a collection of candidate names, not a bare string; pass a list or set.")
    if family is not None and set(pvalues) != set(family):
        missing, extra = sorted(set(family) - set(pvalues)), sorted(set(pvalues) - set(family))
        raise ValueError(f"p-values do not match the pre-registered family (missing {missing}, extra {extra})")
    for name, p in pvalues.items():
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"p-value for {name!r} must be in [0, 1], got {p}")
    m = len(pvalues)
    out = {name: False for name in pvalues}
    for i, (name, p) in enumerate(sorted(pvalues.items(), key=lambda kv: kv[1])):
        if p > alpha / (m - i):
            break
        out[name] = True
    return out


def _paired(p: Any, y: Any) -> tuple[np.ndarray, np.ndarray]:
    pa, ya = _as_float_array(p, "p"), _as_float_array(y, "y")
    if pa.size != ya.size:
        raise ValueError(f"p ({pa.size}) and y ({ya.size}) differ in length")
    if pa.size < 1:
        raise ValueError("need at least one observation")
    if not (np.all(np.isfinite(pa)) and np.all(np.isfinite(ya))):
        raise ValueError("p and y must be finite")
    return pa, ya


def binary_log_loss(p: np.ndarray, y: np.ndarray) -> float:
    """Mean -[y ln p + (1 - y) ln(1 - p)]; p clipped to [1e-9, 1 - 1e-9], y may be fractional."""
    pa, ya = _paired(p, y)
    pc = np.clip(pa, _P_MIN, 1.0 - _P_MIN)
    return float(np.mean(-(ya * np.log(pc) + (1.0 - ya) * np.log1p(-pc))))


def categorical_log_loss(p_of_outcome: np.ndarray) -> float:
    """Mean -ln(p assigned to the realised outcome); p clipped to [1e-9, 1 - 1e-9]."""
    pa = _as_float_array(p_of_outcome, "p_of_outcome")
    if pa.size < 1 or not np.all(np.isfinite(pa)):
        raise ValueError("need at least one finite probability")
    return float(np.mean(-np.log(np.clip(pa, _P_MIN, 1.0 - _P_MIN))))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    """Mean squared error between probability and outcome."""
    pa, ya = _paired(p, y)
    return float(np.mean((pa - ya) ** 2))


def calibration(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[tuple[float, float, int]]:
    """(mean p, mean y, count) per equal-width bin on [0, 1]; empty bins skipped, p = 1 in the last."""
    pa, ya = _paired(p, y)
    if bins < 1:
        raise ValueError(f"bins must be >= 1, got {bins}")
    if np.any(pa < 0.0) or np.any(pa > 1.0):
        raise ValueError("p must be in [0, 1]")
    which = np.minimum((pa * bins).astype(np.int64), bins - 1)
    out: list[tuple[float, float, int]] = []
    for i in range(bins):
        mask = which == i
        n = int(mask.sum())
        if n:
            out.append((float(pa[mask].mean()), float(ya[mask].mean()), n))
    return out


__all__ = [
    "Estimate",
    "binary_log_loss",
    "brier",
    "calibration",
    "categorical_log_loss",
    "cluster_bootstrap",
    "clv",
    "holm",
    "paired_cluster_bootstrap",
]
