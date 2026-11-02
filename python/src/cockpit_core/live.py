# ruff: noqa: TRY004 (contract: every invalid argument raises ValueError, never TypeError)
"""The live consensus (consensus-loo-v1): a selection's fair price from the other books' current lines.

Leave-one-out: the book being priced is excluded, so its own line never pulls the fair price toward itself.
Only books that price the whole market count; each is de-vigged to 1 and the per-selection mean is rounded to
6 dp, so every run gets the same digits.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from cockpit_core.canonical import fmt_prob
from cockpit_core.devig import devig
from cockpit_core.odds import Method, implied

LIVE_RULE = "consensus-loo-v1"
LIVE_MIN_BOOKS = 3

__all__ = ["LIVE_MIN_BOOKS", "LIVE_RULE", "LiveFair", "live_fair"]


@dataclass(frozen=True)
class LiveFair:
    fair: dict[str, str]  # selection -> fmt_prob of the mean: 6 dp, half-up; sorted keys
    books: tuple[str, ...]  # contributing books, code-point sorted
    rule: str
    method: str


def _read_quotes(quotes: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, float]]:
    """Every book's quotes, checked (the excluded book's too)."""
    if not isinstance(quotes, Mapping):
        raise ValueError(f"quotes must be a mapping of book to selection odds, got {type(quotes).__name__}")
    out: dict[str, dict[str, float]] = {}
    for book, lines in quotes.items():
        if not isinstance(book, str) or not book:
            raise ValueError(f"book names must be non-empty strings, got {book!r}")
        if not isinstance(lines, Mapping):
            raise ValueError(f"quotes for book {book!r} must be a mapping, got {type(lines).__name__}")
        for sel, odds in lines.items():
            if not isinstance(sel, str):
                raise ValueError(f"selection keys must be strings, got {sel!r} in book {book!r}")
            implied(odds)  # decimal odds > 1, or ValueError
            if not math.isfinite(odds):  # implied(inf) is 0.0, a probability-0 runner
                raise ValueError(f"decimal odds must be finite, got {odds!r} for {sel!r} in book {book!r}")
        out[book] = dict(lines)
    return out


def live_fair(
    quotes: Mapping[str, Mapping[str, float]],
    *,
    exclude: str | None,
    method: Method | str = "power",
    min_books: int = LIVE_MIN_BOOKS,
) -> LiveFair | None:
    """The consensus-loo-v1 fair probability of each selection of one market, from every book but `exclude`.

    `quotes` maps book -> selection -> decimal odds for ONE single-winner market. The field is every selection
    any book in `quotes` prices, the excluded book included. A book counts when it prices the whole field and
    is not `exclude` (None excludes nothing; a name absent from `quotes` excludes nothing either). Each counted
    book is de-vigged with `method` to 1, and a selection's fair probability is the mean (math.fsum) of the
    counted books' probabilities, formatted by fmt_prob. Returns None when fewer than `min_books` books count,
    or when the field is empty. `min_books` may be raised above LIVE_MIN_BOOKS (3) but not lowered, so the
    `rule` label always holds. Callers pass one market's quotes with a normalised selection set: when a book
    quotes a selection no other book prices, at most that book covers the field, so fewer than `min_books`
    books count and the result is None for every `exclude`. Sum(fair) is within about len(fair) * 5e-7 of 1
    (6 dp rounding), so never assert it equals 1.

    Deterministic: books are processed in code-point order, whatever the input order. Raises ValueError before
    any work for an unknown method, a `min_books` that is not an int >= LIVE_MIN_BOOKS (a bool is rejected),
    an `exclude` that is neither None nor a non-empty string, `quotes` that is not a mapping, a book name that
    is not a non-empty string, a book's quotes that are not a mapping, a non-string selection key, or odds (in
    any book, the excluded one included) that are not finite decimal odds > 1. A de-vig that fails (a
    one-selection field, for one) or a mean that rounds outside (0, 1) at 6 dp also raises ValueError.
    """
    try:
        method = Method(method)
    except ValueError:
        raise ValueError(f"unknown de-vig method {method!r}") from None
    if isinstance(min_books, bool) or not isinstance(min_books, int) or min_books < LIVE_MIN_BOOKS:
        raise ValueError(f"min_books must be an int >= {LIVE_MIN_BOOKS} (the {LIVE_RULE} floor), got {min_books!r}")
    if exclude is not None and (not isinstance(exclude, str) or not exclude):
        raise ValueError(f"exclude must be None or a non-empty book name, got {exclude!r}")
    lines = _read_quotes(quotes)

    field = sorted({sel for book_lines in lines.values() for sel in book_lines})
    books = tuple(sorted(b for b in lines if b != exclude and all(sel in lines[b] for sel in field)))
    if not field or len(books) < min_books:
        return None

    probs = [devig([lines[b][sel] for sel in field], method, expected_total=1.0) for b in books]
    fair = {sel: fmt_prob(math.fsum(p[i] for p in probs) / len(books)) for i, sel in enumerate(field)}
    return LiveFair(fair=fair, books=books, rule=LIVE_RULE, method=method.value)
