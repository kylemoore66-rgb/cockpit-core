from decimal import ROUND_HALF_UP, Decimal

import pytest

from cockpit_core.odds import american_from_decimal, decimal_from_american, implied


def test_conversions_match_fixture(cases):
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
