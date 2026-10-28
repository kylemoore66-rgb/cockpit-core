import re

import pytest

from cockpit_core.canonical import fmt_prob
from cockpit_core.consensus import (
    CONSENSUS_RULE,
    COVERAGE_MIN,
    COVERAGE_MIN_TEXT,
    MIN_BOOKS,
    ConsensusResult,
    consensus_close,
)
from cockpit_core.devig import estimator_probs
from cockpit_core.odds import Method


def books(cases) -> dict[str, dict[str, float]]:
    return {b: dict(sel) for b, sel in cases["consensus"]["closes"].items()}


def run(cases, method, n, closes=None):
    fx = cases["consensus"]
    return consensus_close(
        books(cases) if closes is None else closes, reference_books=fx["reference_books"], method=method, n_winners=n
    )


def test_constants():
    assert (CONSENSUS_RULE, COVERAGE_MIN_TEXT, MIN_BOOKS) == ("consensus-v1", "0.90", 2)
    assert str(COVERAGE_MIN) == "9/10"


def test_multiplicative_vector(cases):
    r = run(cases, "multiplicative", 1)
    assert {s: r.rows[s].fair_prob for s in ("s01", "s04", "s10")} == {
        "s01": "0.260155",
        "s04": "0.098841",
        "s10": "0.024811",
    }
    assert r.rows["s01"].books == ("alpha", "bravo", "charlie") and r.rows["s10"].books == ("alpha", "bravo")
    assert r.dropped_books == {"delta": "coverage"} and r.coverage_min == "0.90" and r.rule == "consensus-v1"
    assert r.method is Method.MULTIPLICATIVE and r.n_winners == 1
    assert r.reference_books == ("alpha", "bravo", "charlie", "delta")
    assert list(r.rows) == [f"s{i:02d}" for i in range(1, 11)] and r.skipped_selections == {}


def test_power_top3_vector(cases):
    r = run(cases, "power", 3)
    assert (r.rows["s01"].fair_prob, r.rows["s10"].fair_prob) == ("0.543031", "0.149050")


def test_shin_single_winner_vector(cases):
    r = run(cases, "shin", 1)
    assert (r.rows["s01"].fair_prob, r.rows["s10"].fair_prob) == ("0.282192", "0.016511")


def test_method_enum_and_string_agree(cases):
    assert run(cases, Method.POWER, 3) == run(cases, "power", 3)


def test_shin_refused_for_multi_winner(cases):
    with pytest.raises(ValueError, match="single-winner"):
        run(cases, "shin", 3)


def test_coverage_boundary_golf_field():
    field = [f"p{i:03d}" for i in range(1, 133)]
    closes = {
        "alpha": dict.fromkeys(field, 100.0),
        "bravo": dict.fromkeys(field, 100.0),
        "charlie": dict.fromkeys(field[:119], 100.0),  # 119/132 = 0.9015: covered
        "delta": dict.fromkeys(field[:118], 100.0),  # 118/132 = 0.8939: dropped
    }
    r = consensus_close(
        closes, reference_books=["alpha", "bravo", "charlie", "delta"], method="multiplicative", n_winners=1
    )
    assert r.rows["p001"].books == ("alpha", "bravo", "charlie") and r.dropped_books == {"delta": "coverage"}
    assert r.rows["p132"].books == ("alpha", "bravo")


def test_selection_needs_two_books(cases):
    closes = books(cases)
    del closes["bravo"]["s10"]  # bravo prices s01..s09: 0.9 coverage, kept
    r = run(cases, "multiplicative", 1, closes)
    assert r.skipped_selections == {"s10": "too_few_books"} and "s10" not in r.rows
    assert r.rows["s01"].books == ("alpha", "bravo", "charlie")


def test_extreme_longshot_is_skipped_not_fatal(cases):
    closes = books(cases)
    closes["alpha"]["s10"] = closes["bravo"]["s10"] = 5_000_000.0
    r = run(cases, "multiplicative", 1, closes)
    assert r.skipped_selections == {"s10": "out_of_range"}
    assert sorted(r.rows) == [f"s{i:02d}" for i in range(1, 10)]


def test_reference_book_without_closes_is_dropped(cases):
    fx = cases["consensus"]
    r = consensus_close(books(cases), reference_books=[*fx["reference_books"], "foxtrot"], method="power", n_winners=1)
    assert r.dropped_books == {"delta": "coverage", "foxtrot": "no_closes"}
    closes = books(cases) | {"foxtrot": {}}
    r = consensus_close(closes, reference_books=[*fx["reference_books"], "foxtrot"], method="power", n_winners=1)
    assert r.dropped_books == {"delta": "coverage", "foxtrot": "no_closes"}


def test_book_that_cannot_devig_is_dropped():
    closes = {"alpha": {"a": 1.5, "b": 2.5}, "bravo": {"a": 1.6, "b": 2.4}}  # n_winners 2 >= 2 priced runners
    r = consensus_close(closes, reference_books=["alpha", "bravo"], method="multiplicative", n_winners=2)
    assert r.dropped_books == {"alpha": "devig_failed", "bravo": "devig_failed"}
    assert r.rows == {} and r.skipped_selections == {"a": "too_few_books", "b": "too_few_books"}


def test_book_whose_shape_raises_is_left_out_of_estimates_but_still_devigged():
    sel = [f"s{i:02d}" for i in range(1, 11)]
    alpha = dict(zip(sel, [1.02, 1.03, 1.04, 1.05, 1.06, 1.08, 1.1, 1.12, 1.15, 1.2], strict=True))
    bravo = {s: o + 0.01 for s, o in alpha.items()}
    charlie = {s: alpha[s] for s in sel[:9]}  # misses s10
    delta = {s: alpha[s] for s in sel[1:]}  # misses s01
    with pytest.raises(ValueError):
        estimator_probs(list(charlie.values()), Method.POWER, 9)  # no power root over charlie's 9 runners
    closes = {"alpha": alpha, "bravo": bravo, "charlie": charlie, "delta": delta}
    r = consensus_close(closes, reference_books=list(closes), method="power", n_winners=9)
    assert r.dropped_books == {} and r.rows["s02"].books == ("alpha", "bravo", "charlie", "delta")
    without = consensus_close(
        {b: closes[b] for b in ("alpha", "bravo", "delta")}, reference_books=["alpha", "bravo", "delta"],
        method="power", n_winners=9,
    )  # fmt: skip
    assert r.rows["s10"] == without.rows["s10"]  # delta's s01 estimate never read charlie's failed shape


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"rule": "consensus-v2"}, "rule"),
        ({"n_winners": True}, "n_winners"),
        ({"n_winners": 0}, "n_winners"),
        ({"n_winners": 1.0}, "n_winners"),
        ({"reference_books": ["alpha"]}, "reference"),
        ({"reference_books": ["alpha", "alpha"]}, "reference"),
        ({"reference_books": ["alpha", ""]}, "reference"),
        ({"reference_books": "alpha"}, "reference"),
        ({"method": "logit"}, "method"),
    ],
)
def test_unknown_rule_and_bad_inputs_rejected(cases, kwargs, match):
    args = {"reference_books": cases["consensus"]["reference_books"], "method": "power", "n_winners": 1} | kwargs
    with pytest.raises(ValueError, match=match):
        consensus_close(books(cases), **args)


def test_bad_closes_rejected(cases):
    ref = cases["consensus"]["reference_books"]
    with pytest.raises(ValueError, match="selection"):
        consensus_close(books(cases) | {"alpha": {1: 3.0}}, reference_books=ref, method="power", n_winners=1)
    with pytest.raises(ValueError, match="decimal odds"):
        consensus_close(books(cases) | {"alpha": {"s01": 1.0}}, reference_books=ref, method="power", n_winners=1)
    with pytest.raises(ValueError, match="decimal odds"):
        consensus_close(books(cases) | {"delta": {"s01": None}}, reference_books=ref, method="power", n_winners=1)
    with pytest.raises(ValueError, match="closes"):
        consensus_close(books(cases) | {"alpha": None}, reference_books=ref, method="power", n_winners=1)


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_non_finite_reference_odds_rejected(cases, bad):
    # implied(inf) is 0.0, so an infinite quote would otherwise count toward coverage with probability 0.
    ref = cases["consensus"]["reference_books"]
    closes = books(cases)
    closes["alpha"] = closes["alpha"] | {"s01": bad}
    with pytest.raises(ValueError, match="decimal odds"):
        consensus_close(closes, reference_books=ref, method="multiplicative", n_winners=1)
    unread = books(cases) | {"echo": {"s01": bad}}  # a non-reference book is never read
    assert consensus_close(unread, reference_books=ref, method="multiplicative", n_winners=1) == run(
        cases, "multiplicative", 1
    )


def test_non_reference_books_ignored(cases):
    closes = books(cases) | {"echo": {"s01": 1.01, "s99": 2.0, 7: "not read"}}
    assert run(cases, "power", 1, closes) == run(cases, "power", 1)


def test_deterministic_across_input_order(cases):
    rev = {b: dict(reversed(sel.items())) for b, sel in reversed(books(cases).items())}
    fx = cases["consensus"]
    for method, n in (("multiplicative", 1), ("power", 3), ("shin", 1)):
        fwd = run(cases, method, n)
        back = consensus_close(rev, reference_books=list(reversed(fx["reference_books"])), method=method, n_winners=n)
        assert isinstance(back, ConsensusResult) and back == fwd
        assert list(back.rows) == list(fwd.rows) and list(back.dropped_books) == list(fwd.dropped_books)


def test_fair_prob_is_six_dp(cases):
    for method, n in (("multiplicative", 1), ("power", 3), ("shin", 1)):
        for row in run(cases, method, n).rows.values():
            assert re.fullmatch(r"0\.[0-9]{6}", row.fair_prob) and row.fair_prob == fmt_prob(row.fair_prob)
