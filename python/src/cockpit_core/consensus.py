# ruff: noqa: TRY004 (contract: every invalid argument raises ValueError, never TypeError)
"""The consensus close (consensus-v1): the pre-registered yardstick a model's closing-line value is graded against.

The mean, over reference books that cover the field, of each book's de-vigged closing line, rounded to 6 dp so
every run and every language gets the same digits. Partial books follow GolfProject's convention (Rulings 71,
77, 89a): de-vigged over the runners they price, to n_winners minus the estimated mass of the runners they miss.
"""

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from cockpit_core.canonical import fmt_prob
from cockpit_core.devig import devig, devig_partial, estimator_probs
from cockpit_core.odds import Method, implied

CONSENSUS_RULE = "consensus-v1"
COVERAGE_MIN = Fraction(9, 10)
COVERAGE_MIN_TEXT = "0.90"
MIN_BOOKS = 2

__all__ = [
    "CONSENSUS_RULE",
    "COVERAGE_MIN",
    "COVERAGE_MIN_TEXT",
    "MIN_BOOKS",
    "ConsensusResult",
    "ConsensusRow",
    "consensus_close",
]


@dataclass(frozen=True)
class ConsensusRow:
    selection: str
    fair_prob: str  # fmt_prob of the mean: 6 dp, half-up
    books: tuple[str, ...]  # contributing books, code-point sorted


@dataclass(frozen=True)
class ConsensusResult:
    rule: str
    method: Method
    n_winners: int
    coverage_min: str
    reference_books: tuple[str, ...]  # sorted
    rows: dict[str, ConsensusRow]  # selections with >= MIN_BOOKS books, sorted keys
    dropped_books: dict[str, str]  # book -> "no_closes" | "coverage" | "devig_failed"
    skipped_selections: dict[str, str]  # selection -> "too_few_books" | "out_of_range"


def _check_args(
    rule: str, method: Method | str, n_winners: int, reference_books: Sequence[str]
) -> tuple[Method, tuple[str, ...]]:
    if rule != CONSENSUS_RULE:
        raise ValueError(f"unknown consensus rule {rule!r}; this library implements {CONSENSUS_RULE!r}")
    try:
        method = Method(method)
    except ValueError:
        raise ValueError(f"unknown de-vig method {method!r}") from None
    if isinstance(n_winners, bool) or not isinstance(n_winners, int) or n_winners < 1:
        raise ValueError(f"n_winners must be an int >= 1, got {n_winners!r}")
    if method == Method.SHIN and n_winners != 1:
        raise ValueError("Shin applies to single-winner markets only")
    if isinstance(reference_books, str) or not isinstance(reference_books, Sequence):
        raise ValueError(f"reference_books must be a sequence of book names, got {reference_books!r}")
    for b in reference_books:
        if not isinstance(b, str) or not b:
            raise ValueError(f"reference book names must be non-empty strings, got {b!r}")
    refs = tuple(sorted(set(reference_books)))
    if len(refs) < MIN_BOOKS:
        raise ValueError(f"need at least {MIN_BOOKS} distinct reference books, got {len(refs)}")
    return method, refs


def _read_closes(closes: Mapping[str, Mapping[str, float]], refs: tuple[str, ...]) -> dict[str, dict[str, float]]:
    """The reference books' closing lines, checked; a book absent from closes reads as empty."""
    if not isinstance(closes, Mapping):
        raise ValueError(f"closes must be a mapping of book to selection odds, got {type(closes).__name__}")
    out: dict[str, dict[str, float]] = {}
    for book in refs:
        lines = closes.get(book, {})
        if not isinstance(lines, Mapping):
            raise ValueError(f"closes for book {book!r} must be a mapping, got {type(lines).__name__}")
        for sel, odds in lines.items():
            if not isinstance(sel, str):
                raise ValueError(f"selection keys must be strings, got {sel!r} in book {book!r}")
            implied(odds)  # decimal odds > 1, or ValueError
            if not math.isfinite(odds):  # implied(inf) is 0.0, which would count toward coverage at probability 0
                raise ValueError(f"decimal odds must be finite, got {odds!r} for {sel!r} in book {book!r}")
        out[book] = dict(lines)
    return out


def consensus_close(
    closes: Mapping[str, Mapping[str, float]],
    *,
    reference_books: Sequence[str],
    method: Method | str,
    n_winners: int,
    rule: str = CONSENSUS_RULE,
) -> ConsensusResult:
    """The consensus-v1 fair probability of each selection of one market, from the books' closing lines.

    `closes` maps book -> selection -> decimal closing odds for ONE market; only `reference_books` are read.
    Expected market shapes: a field market (win, top-N) is one market de-vigged to n_winners (1 for a win,
    N for a top-N); a matchup is its own market (n_winners = 1); a make-cut is one market per player with
    selections "yes" and "no" and n_winners = 1.

    The field is every selection any reference book prices. A book counts when it prices at least
    COVERAGE_MIN of the field (exact fractions). Each counted book is de-vigged with `method` over the runners
    it prices, to n_winners minus the estimated mass of the runners it misses: per missing runner, the median
    of the other counted books' estimator_probs for it (a book whose shape raises drops out of every
    estimate; a runner no other counted book prices adds 0). A book whose de-vig raises is dropped
    ("devig_failed"). A selection's consensus is the mean of its counted books' probabilities, needing
    MIN_BOOKS of them ("too_few_books"), formatted by fmt_prob ("out_of_range" when it rounds outside (0, 1)).

    Deterministic: books and selections are processed in code-point order, whatever the input order. Raises
    ValueError before any work for an unknown rule or method, Shin with n_winners != 1, n_winners not an
    int >= 1, fewer than MIN_BOOKS distinct non-empty reference books, a non-string selection key, or odds
    that are not finite decimal odds > 1.
    """
    method, refs = _check_args(rule, method, n_winners, reference_books)
    lines = _read_closes(closes, refs)

    dropped: dict[str, str] = {}
    field = sorted({sel for book in refs for sel in lines[book]})
    covered: list[str] = []
    for book in refs:
        if not lines[book]:
            dropped[book] = "no_closes"
        elif Fraction(len(lines[book]), len(field)) >= COVERAGE_MIN:
            covered.append(book)
        else:
            dropped[book] = "coverage"

    priced = {book: sorted(lines[book]) for book in covered}
    shapes: dict[str, dict[str, float] | None] = {}
    for book in covered:
        try:
            probs = estimator_probs([lines[book][s] for s in priced[book]], method, n_winners)
            shapes[book] = dict(zip(priced[book], probs, strict=True))
        except ValueError:
            shapes[book] = None  # drops out of every estimate; may still be de-vigged itself

    fair: dict[str, dict[str, float]] = {}
    for book in covered:
        odds = [lines[book][s] for s in priced[book]]
        missing = [s for s in field if s not in lines[book]]
        estimates = []
        for sel in missing:
            others = [shape[sel] for b in covered if b != book and (shape := shapes[b]) is not None and sel in shape]
            if others:  # a runner no other counted book prices adds 0
                estimates.append(statistics.median(others))
        try:
            if missing:
                probs = devig_partial(odds, method, n_winners - math.fsum(estimates))
            else:
                probs = devig(odds, method, n_winners)
        except ValueError:
            dropped[book] = "devig_failed"
            continue
        fair[book] = dict(zip(priced[book], probs, strict=True))

    rows: dict[str, ConsensusRow] = {}
    skipped: dict[str, str] = {}
    for sel in field:
        contributing = tuple(b for b in covered if b in fair and sel in fair[b])
        if len(contributing) < MIN_BOOKS:
            skipped[sel] = "too_few_books"
            continue
        mean = math.fsum(fair[b][sel] for b in contributing) / len(contributing)
        try:
            rows[sel] = ConsensusRow(selection=sel, fair_prob=fmt_prob(mean), books=contributing)
        except ValueError:
            skipped[sel] = "out_of_range"

    return ConsensusResult(
        rule=CONSENSUS_RULE,
        method=method,
        n_winners=n_winners,
        coverage_min=COVERAGE_MIN_TEXT,
        reference_books=refs,
        rows=rows,
        dropped_books=dict(sorted(dropped.items())),
        skipped_selections=skipped,
    )
