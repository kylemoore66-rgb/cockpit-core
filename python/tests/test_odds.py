from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction

import pytest

from cockpit_core.odds import american_from_decimal, decimal_from_american, implied, price_decimal_from_american


def test_conversions_match_fixture(cases):
    assert len(cases["odds_conversion"]) == 11
    checked = 0
    for case in cases["odds_conversion"]:
        american = case["american"]
        if "decimal_4dp" in case:
            got = decimal_from_american(american).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            assert got == Decimal(case["decimal_4dp"]), case
            checked += 1
        if "decimal" in case:
            assert american_from_decimal(Decimal(case["decimal"])) == american, case
            checked += 1
    assert checked == len(cases["odds_conversion"])


@pytest.mark.parametrize("bad", [1.0, 0.5, float("nan"), True, None])
def test_bad_prices_rejected(bad):
    with pytest.raises(ValueError):
        implied(bad)


@pytest.mark.parametrize("bad", [0, 50, -99, 99])
def test_bad_american_rejected(bad):
    with pytest.raises(ValueError):
        decimal_from_american(bad)


@pytest.mark.parametrize("bad", [Decimal(1), Decimal("0.5"), Decimal(0)])
def test_bad_decimal_rejected_for_american(bad):
    with pytest.raises(ValueError):
        american_from_decimal(bad)


# --- price_decimal_from_american: the bet-price storage rule (8 dp, half-up) ---


def test_price_8dp_matches_fixture_as_strings(cases):
    rows = cases["american_8dp"]["cases"]
    assert len(rows) == 11
    for case in rows:
        got = price_decimal_from_american(case["american"])
        assert isinstance(got, Decimal), case
        assert str(got) == case["decimal_8dp"], case  # a storage format: the string itself, 8 places
        assert got.as_tuple().exponent == -8, case


def test_price_8dp_refusals_from_fixture(cases):
    refused = cases["american_8dp"]["refused"]
    assert -100 in refused
    for bad in refused:
        with pytest.raises(ValueError):
            price_decimal_from_american(bad)


@pytest.mark.parametrize("bad", [150.0, -110.0, Decimal(150), Fraction(150), True, False, None, -100, 0, 99, -99])
def test_price_8dp_refuses_non_ints_bools_and_small_or_minus_100(bad):
    with pytest.raises(ValueError):
        price_decimal_from_american(bad)


def test_price_8dp_is_not_decimal_from_american():
    # decimal_from_american keeps precision 40, truncated; the storage rule is 8 dp half-up.
    assert str(decimal_from_american(-110)) == "1.909090909090909090909090909090909090909"
    assert str(price_decimal_from_american(-110)) == "1.90909091"
    assert decimal_from_american(-100) == Decimal(2)  # unchanged: -100 is still accepted there


def test_price_8dp_ignores_caller_context():
    expected = [str(price_decimal_from_american(a)) for a in (-110, -51200, -12345, 1000000)]
    with localcontext() as ctx:
        ctx.traps[Inexact] = True
        ctx.traps[Rounded] = True
        ctx.rounding = ROUND_CEILING
        ctx.prec = 3
        got = [str(price_decimal_from_american(a)) for a in (-110, -51200, -12345, 1000000)]
    assert got == expected


def test_price_8dp_property_every_american_in_range():
    """For every integer a with 100 <= |a| <= 20000, a != -100: the 8 dp value is the exact price rounded
    half-up (checked two independent ways), and american_from_decimal gives a back."""
    eighth = Decimal("0.00000001")
    half_unit = Fraction(1, 2 * 10**8)
    round_trip_failures = []
    checked = 0
    for a in range(-20000, 20001):
        if abs(a) < 100 or a == -100:
            continue
        exact = 1 + Fraction(a, 100) if a > 0 else 1 + Fraction(100, -a)
        got = price_decimal_from_american(a)
        # Oracle 1: the exact fraction as a Decimal (50 digits, truncated, which cannot cross a tie), half-up.
        with localcontext() as ctx:
            ctx.prec = 50
            ctx.rounding = ROUND_DOWN
            oracle = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(eighth, ROUND_HALF_UP)
        assert got == oracle and str(got) == str(oracle), a
        # Oracle 2, in exact Fractions: within half a unit of the 8th place, and a tie goes up.
        error = Fraction(got) - exact
        assert -half_unit < error <= half_unit, a
        if american_from_decimal(got) != a:
            round_trip_failures.append(a)
        checked += 1
    assert checked == 2 * (20000 - 99) - 1
    assert round_trip_failures == []
