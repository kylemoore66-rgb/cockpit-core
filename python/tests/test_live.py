import math
import random
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from cockpit_core.canonical import fmt_prob
from cockpit_core.devig import devig
from cockpit_core.live import LIVE_MIN_BOOKS, LIVE_RULE, LiveFair, live_fair
from cockpit_core.odds import Method

# Synthetic prices only: no real or licensed odds.
MARKET = {
    "a": {"h": 1.91, "v": 1.91},
    "b": {"h": 1.95, "v": 1.87},
    "c": {"h": 1.90, "v": 1.92},
    "d": {"h": 2.30, "v": 1.62},
}


def _hand_mean(q, books, sel) -> Decimal:
    """Exact multiplicative mean over books of (1/o_sel) / sum(1/o), as a 40-digit Decimal for fmt_prob."""
    total = Fraction(0)
    for b in books:
        implied = {s: 1 / Fraction(o) for s, o in q[b].items()}
        total += implied[sel] / sum(implied.values())
    mean = total / len(books)
    with localcontext() as ctx:
        ctx.prec = 40
        return Decimal(mean.numerator) / Decimal(mean.denominator)


def test_constants():
    assert (LIVE_RULE, LIVE_MIN_BOOKS) == ("consensus-loo-v1", 3)


def test_excludes_named_book_multiplicative():
    q = MARKET
    r = live_fair(q, exclude="d", method="multiplicative")
    assert isinstance(r, LiveFair)
    assert r.books == ("a", "b", "c")
    assert (r.rule, r.method) == ("consensus-loo-v1", "multiplicative")
    assert r.fair["h"] == fmt_prob(_hand_mean(q, ["a", "b", "c"], "h"))
    assert r.fair["v"] == fmt_prob(_hand_mean(q, ["a", "b", "c"], "v"))


def test_default_method_is_power():
    r = live_fair(MARKET, exclude="d")
    assert r.method == "power"
    per_book = [devig([MARKET[b]["h"], MARKET[b]["v"]], Method.POWER) for b in ("a", "b", "c")]
    assert r.fair == {
        "h": fmt_prob(math.fsum(p[0] for p in per_book) / 3),
        "v": fmt_prob(math.fsum(p[1] for p in per_book) / 3),
    }


def test_none_when_fewer_than_three_other_books():
    q = {b: MARKET[b] for b in ("a", "b", "d")}
    assert live_fair(q, exclude="d") is None
    assert live_fair(q, exclude=None) is not None  # the same three books count when none is excluded


def test_min_books_override():
    q = {b: MARKET[b] for b in ("a", "b", "d")}
    r = live_fair(q, exclude="d", min_books=2)
    assert r is not None and r.books == ("a", "b")


def test_incomplete_book_does_not_count():
    q = {**MARKET, "e": {"h": 1.80}}  # e misses "v"
    r = live_fair(q, exclude="d", method="multiplicative")
    assert r.books == ("a", "b", "c")
    assert r.fair["h"] == fmt_prob(_hand_mean(q, ["a", "b", "c"], "h"))
    q = {"a": MARKET["a"], "b": MARKET["b"], "e": {"h": 1.80}, "d": MARKET["d"]}
    assert live_fair(q, exclude="d") is None  # only a and b price every selection


def test_union_includes_the_excluded_book():
    # d prices a draw no other book prices, so no other book covers the field and nothing counts.
    q = {**MARKET, "d": {"h": 2.30, "v": 3.10, "x": 3.40}}
    assert live_fair(q, exclude="d") is None


def test_exclude_none_uses_all_books():
    r = live_fair(MARKET, exclude=None, method="multiplicative")
    assert r.books == ("a", "b", "c", "d")
    assert r.fair["h"] == fmt_prob(_hand_mean(MARKET, ["a", "b", "c", "d"], "h"))


def test_exclude_absent_book_uses_all_books():
    assert live_fair(MARKET, exclude="zz").books == ("a", "b", "c", "d")


def test_output_is_sorted_whatever_the_input_order():
    shuffled = {b: dict(reversed(MARKET[b].items())) for b in ("c", "a", "d", "b")}
    r = live_fair(shuffled, exclude=None)
    assert r.books == ("a", "b", "c", "d")
    assert list(r.fair) == ["h", "v"]
    assert r == live_fair(MARKET, exclude=None)


def test_power_fair_sums_to_one_within_6dp():
    rng = random.Random(20261102)
    for _ in range(200):
        n_sel = rng.randint(2, 4)
        n_books = rng.randint(3, 6)
        sels = [f"s{i}" for i in range(n_sel)]
        q = {}
        for b in range(n_books):
            weights = [rng.uniform(0.05, 1.0) for _ in sels]
            margin = rng.uniform(1.01, 1.12)
            total = sum(weights)
            q[f"b{b}"] = {s: max(1.01, total / (w * margin)) for s, w in zip(sels, weights, strict=True)}
        r = live_fair(q, exclude=None)
        assert r is not None
        assert abs(sum(Decimal(p) for p in r.fair.values()) - 1) <= Decimal("2e-6")


@pytest.mark.parametrize("bad", [1.0, 0.5, -2.0, 0.0, float("nan"), float("inf"), True, None, "1.9"])
def test_rejects_price_at_or_below_one(bad):
    q = {**MARKET, "c": {"h": bad, "v": 1.92}}
    with pytest.raises(ValueError, match="decimal odds"):
        live_fair(q, exclude=None)


def test_rejects_bad_price_in_excluded_book():
    q = {**MARKET, "d": {"h": 1.0, "v": 1.62}}
    with pytest.raises(ValueError, match="decimal odds"):
        live_fair(q, exclude="d")


def test_rejects_unknown_method():
    with pytest.raises(ValueError, match="unknown de-vig method"):
        live_fair(MARKET, exclude=None, method="additive")


@pytest.mark.parametrize("bad", [0, -1, True, 2.5, "3"])
def test_rejects_bad_min_books(bad):
    with pytest.raises(ValueError, match="min_books"):
        live_fair(MARKET, exclude=None, min_books=bad)


@pytest.mark.parametrize("bad", ["", 3])
def test_rejects_bad_exclude(bad):
    with pytest.raises(ValueError, match="exclude"):
        live_fair(MARKET, exclude=bad)


def test_rejects_malformed_quotes():
    with pytest.raises(ValueError, match="quotes must be a mapping"):
        live_fair([("a", {"h": 1.9})], exclude=None)
    with pytest.raises(ValueError, match="book names"):
        live_fair({"": {"h": 1.9, "v": 1.9}}, exclude=None)
    with pytest.raises(ValueError, match="must be a mapping"):
        live_fair({"a": [1.9, 1.9]}, exclude=None)
    with pytest.raises(ValueError, match="selection keys"):
        live_fair({"a": {1: 1.9, "v": 1.9}}, exclude=None)


def test_empty_market_is_none():
    assert live_fair({}, exclude=None) is None
    assert live_fair({"a": {}, "b": {}, "c": {}}, exclude=None) is None


def test_single_selection_market_raises():
    with pytest.raises(ValueError, match="expected_total"):
        live_fair({"a": {"h": 1.9}, "b": {"h": 1.9}, "c": {"h": 1.9}}, exclude=None)
