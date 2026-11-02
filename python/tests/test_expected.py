"""Expected profit, profit variance, outcome moments and the cumulative band (shared `expected` fixture).

Results are unrounded (one division at precision 40, truncated), so fixture values are compared by value
(Decimal equality), not as strings. The TS suite checks the same fixture, so the two packages agree.
"""

import math
import random
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from functools import partial

import pytest

from cockpit_core.expected import BandPoint, cumulative_band, expected_profit, outcome_moments, profit_variance
from cockpit_core.settle import HALF_LOSS, HALF_WIN, LOSS, VOID, WIN, Settlement


def _settlement(s: dict) -> Settlement:
    return Settlement(Fraction(s["win"]), Fraction(s["refund"]))


def _outcomes(rows: list) -> list[tuple[str, Settlement]]:
    return [(q, _settlement(s)) for q, s in rows]


# --- the shared fixture ---


def test_binary_matches_fixture(cases):
    rows = cases["expected"]["binary"]
    assert len(rows) == 5
    for c in rows:
        for convert in (Decimal, str):  # Decimal or plain decimal strings
            args = (convert(c["stake"]), convert(c["p"]), convert(c["o"]))
            e = expected_profit(*args)
            v = profit_variance(*args)
            assert isinstance(e, Decimal) and isinstance(v, Decimal), c["name"]
            assert e == Decimal(c["expected_profit"]), c["name"]
            assert v == Decimal(c["variance"]), c["name"]


def test_brief_vector_is_exactly_5_0005(cases):
    c = cases["expected"]["binary"][0]
    assert (c["stake"], c["p"], c["o"]) == ("100", "0.55", "1.9091")
    assert expected_profit("100", "0.55", "1.9091") == Decimal("5.0005")
    exact = Fraction(100) ** 2 * Fraction("1.9091") ** 2 * Fraction("0.55") * Fraction("0.45")
    assert Fraction(profit_variance("100", "0.55", "1.9091")) == exact  # few digits: no truncation at all


def test_outcome_moments_matches_fixture(cases):
    rows = cases["expected"]["outcomes"]
    assert len(rows) == 3
    for c in rows:
        mean, var = outcome_moments(Decimal(c["stake"]), Decimal(c["price"]), _outcomes(c["outcomes"]))
        assert isinstance(mean, Decimal) and isinstance(var, Decimal), c["name"]
        assert mean == Decimal(c["mean"]), c["name"]
        assert var == Decimal(c["variance"]), c["name"]
        # strings work too, for the stake, the price and each probability
        assert outcome_moments(c["stake"], c["price"], _outcomes(c["outcomes"])) == (mean, var), c["name"]


def test_push_case_uses_the_named_settlements():
    mean, var = outcome_moments("10", "2.0", [("0.45", WIN), ("0.10", VOID), ("0.45", LOSS)])
    assert mean == 0 and var == 90


def test_band_matches_fixture(cases):
    rows = cases["expected"]["band"]
    assert len(rows) == 3
    for c in rows:
        bets = [(Decimal(e), Decimal(v)) for e, v in c["bets"]]
        got = cumulative_band(bets)
        assert isinstance(got, list), c["name"]
        assert len(got) == len(c["points"]), c["name"]
        for point, want in zip(got, c["points"], strict=True):
            assert isinstance(point, BandPoint), c["name"]
            assert isinstance(point.expected, Decimal), c["name"]
            assert type(point.sigma) is float, c["name"]
            assert point.expected == Decimal(want["expected"]), c["name"]
            assert point.sigma == want["sigma"], c["name"]


def test_band_running_sum_is_exact_past_40_digits(cases):
    c = next(c for c in cases["expected"]["band"] if c["name"] == "exact_sum_past_40_digits")
    last = cumulative_band([(Decimal(e), Decimal(v)) for e, v in c["bets"]])[-1]
    assert Fraction(last.expected) == Fraction(10**20) + Fraction(1, 10**21)


def test_band_of_fixture_bets_sums_their_moments(cases):
    rows = cases["expected"]["binary"]
    bets = [(expected_profit(c["stake"], c["p"], c["o"]), profit_variance(c["stake"], c["p"], c["o"])) for c in rows]
    band = cumulative_band(bets)
    total_e = sum((Fraction(e) for e, _ in bets), Fraction(0))
    total_v = sum((Fraction(v) for _, v in bets), Fraction(0))
    assert Fraction(band[-1].expected) == total_e
    assert band[-1].sigma == math.sqrt(float(Decimal(total_v.numerator) / Decimal(total_v.denominator)))


def test_band_point_is_frozen():
    point = cumulative_band([(Decimal(1), Decimal(4))])[0]
    assert point == BandPoint(expected=Decimal(1), sigma=2.0)
    with pytest.raises(AttributeError):
        point.sigma = 3.0  # type: ignore[misc]


def test_band_zero_is_never_negative_zero():
    point = cumulative_band([(Decimal("-0"), Decimal("-0"))])[0]
    assert point.expected == 0 and not point.expected.is_signed()
    assert point.sigma == 0.0 and math.copysign(1.0, point.sigma) == 1.0


# --- properties ---


def _random_decimal_string(rng: random.Random, whole_max: int, places: int) -> str:
    return f"{rng.randint(0, whole_max)}.{rng.randint(0, 10**places - 1):0{places}d}"


def test_binary_equals_outcome_moments():
    """For 200 random bets, the binary formulas equal outcome_moments over WIN with p and LOSS with 1 - p."""
    rng = random.Random(20261102)
    for _ in range(200):
        stake = _random_decimal_string(rng, 5000, 2)
        p = Decimal(f"0.{rng.randint(0, 10**6 - 1):06d}") if rng.random() < 0.95 else Decimal(rng.choice(("0", "1")))
        q = Decimal(1) - p  # exact: few digits
        o = Decimal(f"{rng.randint(1, 200)}.{rng.randint(1, 9999):04d}")
        mean, var = outcome_moments(stake, o, [(p, WIN), (q, LOSS)])
        assert profit_variance(stake, p, o) == var, (stake, p, o)
        assert expected_profit(stake, p, o) == mean, (stake, p, o)


def test_outcome_moments_match_exact_fractions():
    """The two moments are the exact mean and variance, divided once (precision 40, truncated)."""
    rng = random.Random(7)
    settlements = [WIN, LOSS, VOID, HALF_WIN, HALF_LOSS, Settlement(Fraction(1, 3), Fraction(0))]
    for _ in range(100):
        stake = Decimal(_random_decimal_string(rng, 1000, 2))
        o = Decimal(f"{rng.randint(1, 50)}.{rng.randint(1, 999):03d}")
        weights = [rng.randint(0, 1000) for _ in settlements]
        weights[0] += 1
        total = sum(weights)
        probs = [Fraction(w, total) for w in weights]
        # decimal probabilities that sum to exactly 1: round all but the last, give it the remainder
        qs = [Decimal(f"{float(x):.6f}") for x in probs[:-1]]
        last = Decimal(1) - sum(qs, Decimal(0))
        if last < 0:
            continue
        qs.append(last)
        outcomes = list(zip(qs, settlements, strict=True))
        b, price = Fraction(stake), Fraction(o)
        xs = [(Fraction(q), b * (s.win * price + s.refund - 1)) for q, s in outcomes]
        m = sum((q * x for q, x in xs), Fraction(0))
        v = sum((q * (x - m) ** 2 for q, x in xs), Fraction(0))
        mean, var = outcome_moments(stake, o, outcomes)
        with localcontext() as ctx:
            ctx.prec = 40
            ctx.rounding = ROUND_DOWN
            assert mean == Decimal(m.numerator) / Decimal(m.denominator)
            assert var == Decimal(v.numerator) / Decimal(v.denominator)
        assert var >= 0


# --- validation ---


@pytest.mark.parametrize(
    "probs",
    [
        ("0.5", "0.49"),
        ("0.5", "0.51"),
        ("0.3333333333", "0.3333333333", "0.3333333333"),
        ("0.5", "0.5", "0.0000000001"),
        ("0.99",),
    ],
)
def test_outcomes_must_sum_to_one(probs):
    outcomes = [(q, WIN if i == 0 else LOSS) for i, q in enumerate(probs)]
    with pytest.raises(ValueError, match="sum to exactly 1"):
        outcome_moments("10", "2", outcomes)


def test_outcomes_summing_to_exactly_one_are_accepted():
    assert outcome_moments("10", "2", [("1", WIN)]) == (Decimal(10), Decimal(0))
    assert outcome_moments("10", "2", [("0.1", WIN), ("0.2", LOSS), ("0.7", LOSS)])[0] == Decimal(-8)
    assert outcome_moments("10", "2", [("0", WIN), ("1.000", LOSS)]) == (Decimal(-10), Decimal(0))


def test_no_outcomes_is_rejected():
    with pytest.raises(ValueError):
        outcome_moments("10", "2", [])


@pytest.mark.parametrize("bad", ["-0.1", "1.1", Decimal("-0.1"), Decimal("1.0000001")])
def test_outcome_probability_must_be_in_0_1(bad):
    with pytest.raises(ValueError, match="outcome probability"):
        outcome_moments("10", "2", [(bad, WIN), (Decimal(1) - Decimal(bad), LOSS)])


@pytest.mark.parametrize("bad", [None, "win", (1, 0), {"win": "1/1", "refund": "0/1"}])
def test_outcome_settlement_must_be_a_settlement(bad):
    with pytest.raises(TypeError, match="must be a Settlement"):
        outcome_moments("10", "2", [("1", bad)])


@pytest.mark.parametrize("bad", [None, "1", ("1",), ("1", WIN, WIN), [("1", WIN, "x")], 5])
def test_outcomes_must_be_pairs(bad):
    outcomes = bad if isinstance(bad, list) else [bad]
    with pytest.raises(ValueError, match="outcomes must be"):
        outcome_moments("10", "2", outcomes)


@pytest.mark.parametrize("bad", [None, "1", b"x", 5, {"1": WIN}])
def test_outcomes_must_be_a_sequence(bad):
    with pytest.raises(ValueError, match="outcomes must be"):
        outcome_moments("10", "2", bad)


def test_outcomes_may_be_a_tuple_of_lists():
    assert outcome_moments("10", "2", (["0.5", WIN], ["0.5", LOSS])) == (Decimal(0), Decimal(100))


BAD_NUMBERS = [
    None,
    True,
    1,
    1.5,
    Fraction(1, 2),
    Decimal("NaN"),
    Decimal("Infinity"),
    "",
    " 1",
    "1 ",
    "1\n",
    "+1",
    "-1",
    "1e2",
    "1_0",
    ".5",
    "5.",
    "١",  # an Arabic-Indic digit: not a plain ASCII decimal
    "NaN",
    "Infinity",
    Decimal("1e30"),
    Decimal("1e-61"),
]


@pytest.mark.parametrize("bad", BAD_NUMBERS)
def test_bad_stake_rejected(bad):
    with pytest.raises(ValueError):
        expected_profit(bad, "0.5", "2")
    with pytest.raises(ValueError):
        profit_variance(bad, "0.5", "2")
    with pytest.raises(ValueError):
        outcome_moments(bad, "2", [("1", WIN)])


@pytest.mark.parametrize("bad", BAD_NUMBERS)
def test_bad_probability_rejected(bad):
    with pytest.raises(ValueError):
        expected_profit("10", bad, "2")
    with pytest.raises(ValueError):
        profit_variance("10", bad, "2")
    with pytest.raises(ValueError):
        outcome_moments("10", "2", [(bad, WIN)])


@pytest.mark.parametrize("bad", BAD_NUMBERS)
def test_bad_price_rejected(bad):
    with pytest.raises(ValueError):
        expected_profit("10", "0.5", bad)
    with pytest.raises(ValueError):
        profit_variance("10", "0.5", bad)
    with pytest.raises(ValueError):
        outcome_moments("10", bad, [("1", WIN)])


@pytest.mark.parametrize("fn", [expected_profit, profit_variance])
def test_value_ranges(fn):
    with pytest.raises(ValueError, match="stake"):
        fn(Decimal(-1), "0.5", "2")
    with pytest.raises(ValueError, match="fair_prob"):
        fn("10", Decimal("-0.1"), "2")
    with pytest.raises(ValueError, match="fair_prob"):
        fn("10", "1.1", "2")
    for price in ("1", "0.5", "0"):
        with pytest.raises(ValueError, match="price"):
            fn("10", "0.5", price)
    assert fn("0", "0.5", "2") == 0  # a zero stake is fine


def test_outcome_moments_value_ranges():
    with pytest.raises(ValueError, match="stake"):
        outcome_moments(Decimal(-1), "2", [("1", WIN)])
    with pytest.raises(ValueError, match="price"):
        outcome_moments("10", "1", [("1", WIN)])


@pytest.mark.parametrize(
    "bad",
    [
        [("5", "9")],  # strings are not accepted here
        [(5, 9)],
        [(Decimal("NaN"), Decimal(1))],
        [(Decimal(1), Decimal("Infinity"))],
        [(Decimal(1), Decimal(-1))],  # a variance is never negative
        [(Decimal("1e30"), Decimal(1))],
        [(Decimal(1), Decimal("1e-61"))],
        [(Decimal(1),)],
        [(Decimal(1), Decimal(1), Decimal(1))],
        [Decimal(1)],
        None,
        "bets",
    ],
)
def test_band_rejects_bad_bets(bad):
    with pytest.raises(ValueError):
        cumulative_band(bad)


def test_band_accepts_negative_expected_and_a_tuple():
    band = cumulative_band(((Decimal("-1.5"), Decimal(0)), (Decimal("-0.5"), Decimal("0.25"))))
    assert [p.expected for p in band] == [Decimal("-1.5"), Decimal(-2)]
    assert [p.sigma for p in band] == [0.0, 0.5]


# --- the caller's decimal context is ignored ---


def _hostile(fn):
    with localcontext() as ctx:
        ctx.traps[Inexact] = True
        ctx.traps[Rounded] = True
        ctx.rounding = ROUND_CEILING
        ctx.prec = 3
        ctx.capitals = 0
        return fn()


def test_ignores_caller_context(cases):
    for c in cases["expected"]["binary"]:
        args = (Decimal(c["stake"]), Decimal(c["p"]), Decimal(c["o"]))
        assert _hostile(partial(expected_profit, *args)) == expected_profit(*args)
        assert str(_hostile(partial(profit_variance, *args))) == str(profit_variance(*args))
        assert _hostile(partial(expected_profit, *map(str, args))) == expected_profit(*args)
    for c in cases["expected"]["outcomes"]:
        args = (c["stake"], c["price"], _outcomes(c["outcomes"]))
        assert _hostile(partial(outcome_moments, *args)) == outcome_moments(*args)
    for c in cases["expected"]["band"]:
        bets = [(Decimal(e), Decimal(v)) for e, v in c["bets"]]
        assert _hostile(partial(cumulative_band, bets)) == cumulative_band(bets)
