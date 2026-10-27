"""Shared domain limits: money inputs are bounded, and decimal exponents are bounded before any digits are expanded.

The fixture section ``domain_limits`` is asserted by the TS suite too (test/domain-limits.test.ts), so both
languages accept and reject exactly the same values.

* Money inputs (bankroll, stake, exposures, prices and every other Decimal entering money math):
  ``|x| >= 1e30`` raises ValueError.
* Any non-zero Decimal entering money math or ``fmt_prob``/``fmt_price`` whose leading digit sits beyond
  ``10**60`` or below ``10**-60`` (``adjusted()`` outside [-60, 60]) raises ValueError at once, so
  ``1e-100000000`` cannot make the library build a 100-million-digit integer.
* Zero is zero whatever its exponent.
"""

import json
import time
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

import pytest

from cockpit_core.canonical import fmt_price, fmt_prob
from cockpit_core.kelly import StakeSettings, size_stake
from cockpit_core.odds import american_from_decimal
from cockpit_core.settle import WIN, Settlement, profit

FAST_SECONDS = 1.0
MAX_MESSAGE = 200
FIXTURE_CASES = json.loads((Path(__file__).parents[2] / "fixtures" / "cases.json").read_text(encoding="utf-8"))[
    "domain_limits"
]


def _run(case: dict) -> Decimal | str | int:
    fn = case["fn"]
    if fn == "stake":
        return size_stake(
            fair_prob=Decimal(case["fair_prob"]),
            price=Decimal(case["price"]),
            bankroll=Decimal(case["bankroll"]),
            settings=StakeSettings(
                kelly_multiplier=Decimal(case["kelly_multiplier"]),
                bet_cap=Decimal(case["bet_cap"]),
                participant_cap=Decimal(case["participant_cap"]),
                event_cap=Decimal(case["event_cap"]),
            ),
            participant_exposure=Decimal(case["participant_exposure"]),
            event_exposure=Decimal(case["event_exposure"]),
        )
    if fn == "profit":
        s = Settlement(Fraction(case["win"]), Fraction(case["refund"]))
        return profit(Decimal(case["stake"]), Decimal(case["price"]), s)
    if fn == "fmt_price":
        return fmt_price(Decimal(case["value"]))
    if fn == "fmt_prob":
        return fmt_prob(Decimal(case["value"]))
    if fn == "american_from_decimal":
        return american_from_decimal(Decimal(case["value"]))
    raise AssertionError(f"unknown fn {fn!r}")


def test_domain_limits_section_shape(cases):
    assert len(cases["domain_limits"]) == 15
    assert [c["name"] for c in cases["domain_limits"]] == [c["name"] for c in FIXTURE_CASES]


@pytest.mark.parametrize("case", FIXTURE_CASES, ids=lambda c: c["name"])
def test_domain_limits_match_fixture(case):
    start = time.perf_counter()
    if case.get("error"):
        with pytest.raises(ValueError) as info:
            _run(case)
        assert len(str(info.value)) < MAX_MESSAGE
    else:
        got = _run(case)
        expected = case["stake"] if case["fn"] == "stake" else case["profit"]
        assert str(got) == expected
        assert not got.is_signed() or expected.startswith("-")
    assert time.perf_counter() - start < FAST_SECONDS


def _stake(**overrides: Decimal) -> Decimal:
    args = {
        "fair_prob": Decimal("0.25"),
        "price": Decimal("5.5"),
        "bankroll": Decimal(10000),
        "participant_exposure": Decimal(0),
        "event_exposure": Decimal(0),
    }
    args.update(overrides)
    return size_stake(settings=StakeSettings(), **args)


@pytest.mark.parametrize("name", ["bankroll", "price", "participant_exposure", "event_exposure"])
@pytest.mark.parametrize("value", ["1e30", "-1e30", "1E+31", "1e60", "1e61", "1e20000000"])
def test_stake_money_inputs_at_or_past_1e30_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        _stake(**{name: Decimal(value)})


@pytest.mark.parametrize("name", ["fair_prob", "bankroll", "price", "participant_exposure", "event_exposure"])
@pytest.mark.parametrize("value", ["1e-61", "-1e-61", "1e-100000000", "1.5e-61"])
def test_stake_exponent_below_minus_60_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        _stake(**{name: Decimal(value)})


def test_stake_bounds_are_inclusive_where_documented():
    assert str(_stake(bankroll=Decimal("1e-60"))) == "0.00"
    assert str(_stake(bankroll=Decimal("9.99e29"))) == "19980000000000000000000000000.00"
    assert str(_stake(participant_exposure=Decimal("0E-100000000"), event_exposure=Decimal("0E+100000000"))) == "200.00"


@pytest.mark.parametrize("name", ["kelly_multiplier", "bet_cap", "participant_cap", "event_cap"])
def test_stake_settings_share_the_exponent_limit(name):
    with pytest.raises(ValueError, match=name):
        StakeSettings(**{name: Decimal("1e-61")})
    StakeSettings(**{name: Decimal("1e-60")})


@pytest.mark.parametrize("value", ["1e30", "-1e30", "1e-61", "1e-100000000", "1e20000000"])
def test_profit_stake_limits(value):
    with pytest.raises(ValueError, match="stake"):
        profit(Decimal(value), Decimal(2), WIN)


@pytest.mark.parametrize("value", ["1e30", "1e20000000", "1." + "0" * 70 + "1"])
def test_profit_price_limits(value):
    # 1.000...0001 has its leading digit at 10**0 but 72 fraction digits: it is within the exponent limit
    # and is a valid price just above 1, so only the first two are rejected
    if value.startswith("1."):
        assert str(profit(Decimal(1), Decimal(value), WIN)) == "0.00"
    else:
        with pytest.raises(ValueError, match="price"):
            profit(Decimal(1), Decimal(value), WIN)


@pytest.mark.parametrize("value", ["1e30", "1e61", "1e20000000"])
def test_american_from_decimal_shares_the_money_limit(value):
    with pytest.raises(ValueError, match="decimal odds"):
        american_from_decimal(Decimal(value))


@pytest.mark.parametrize("fn", [fmt_prob, fmt_price])
@pytest.mark.parametrize(
    "value", [Decimal("1e61"), Decimal("1e-61"), Decimal("1e20000000"), Decimal("1e-100000000"), 1e300, 5e-324]
)
def test_formatting_exponent_limit(fn, value):
    start = time.perf_counter()
    with pytest.raises(ValueError):
        fn(value)
    assert time.perf_counter() - start < FAST_SECONDS


def test_messages_echo_at_most_about_40_characters_of_the_value():
    long_value = Decimal("1" * 5000)
    for call in (
        lambda: _stake(bankroll=long_value),
        lambda: profit(long_value, Decimal(2), WIN),
        lambda: fmt_price(long_value),
        lambda: american_from_decimal(long_value),
    ):
        with pytest.raises(ValueError) as info:
            call()
        assert len(str(info.value)) < MAX_MESSAGE


HOSTILE = [
    Decimal("sNaN"),
    Decimal("NaN"),
    Decimal("-Infinity"),
    Decimal("1e999999"),
    Decimal("-1e-999999"),
    Decimal("9" * 200),
    Decimal("1e29") * 9,
]


@pytest.mark.parametrize("value", HOSTILE, ids=str)
def test_public_money_apis_never_raise_invalid_operation(value):
    calls = [
        lambda: _stake(bankroll=value),
        lambda: _stake(price=value),
        lambda: _stake(fair_prob=value),
        lambda: profit(value, Decimal(2), WIN),
        lambda: profit(Decimal(1), value, WIN),
        lambda: american_from_decimal(value),
        lambda: fmt_prob(value),
        lambda: fmt_price(value),
    ]
    for call in calls:
        try:
            call()
        except ValueError:
            pass
        except InvalidOperation as exc:  # pragma: no cover - the failure being guarded against
            pytest.fail(f"decimal.InvalidOperation escaped: {exc!r}")
