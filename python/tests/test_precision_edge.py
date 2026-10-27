"""Shared precision-edge fixtures: values a hair under a rounding boundary must not be lifted onto it.

The same cases are asserted by the TS suite, so the truncating single division is CI-enforced there too.
"""

from decimal import Decimal
from fractions import Fraction

from cockpit_core.kelly import StakeSettings, size_stake
from cockpit_core.settle import Settlement, profit


def _stake(case: dict) -> Decimal:
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


def _profit(case: dict) -> Decimal:
    s = Settlement(Fraction(case["win"]), Fraction(case["refund"]))
    return profit(Decimal(case["stake"]), Decimal(case["price"]), s)


def test_precision_edge_matches_fixture(cases):
    section = cases["precision_edge"]
    assert len(section) == 3
    assert sorted(c["kind"] for c in section) == ["profit", "profit", "stake"]
    for case in section:
        if case["kind"] == "stake":
            got, expected = _stake(case), case["stake"]
        else:
            got, expected = _profit(case), case["profit"]
        assert str(got) == expected, case["name"]
        assert not got.is_signed(), case["name"]
