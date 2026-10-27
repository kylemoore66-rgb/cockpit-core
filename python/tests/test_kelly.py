from decimal import Decimal

import pytest

from cockpit_core.kelly import StakeSettings, edge, full_kelly, size_stake
from cockpit_core.odds import implied


def _stake_kwargs(case: dict) -> dict:
    return {
        "fair_prob": Decimal(case["fair_prob"]),
        "price": Decimal(case["price"]),
        "bankroll": Decimal(case["bankroll"]),
        "settings": StakeSettings(
            kelly_multiplier=Decimal(case["kelly_multiplier"]),
            bet_cap=Decimal(case["bet_cap"]),
            participant_cap=Decimal(case["participant_cap"]),
            event_cap=Decimal(case["event_cap"]),
        ),
        "participant_exposure": Decimal(case["participant_exposure"]),
        "event_exposure": Decimal(case["event_exposure"]),
    }


def _valid_kwargs(**overrides) -> dict:
    kwargs = {
        "fair_prob": Decimal("0.25"),
        "price": Decimal("5.5"),
        "bankroll": Decimal(10000),
        "settings": StakeSettings(),
        "participant_exposure": Decimal(0),
        "event_exposure": Decimal(0),
    }
    kwargs.update(overrides)
    return kwargs


def test_edge_and_kelly_match_fixture(cases):
    assert cases["edge_kelly"]
    for case in cases["edge_kelly"]:
        p, o = float(case["fair_prob"]), float(case["price"])
        assert edge(p, o) == pytest.approx(case["edge"], abs=1e-9), case
        assert full_kelly(p, o) == pytest.approx(case["full_kelly"], abs=1e-9), case


def test_kelly_is_not_tennis_formula():
    assert full_kelly(0.5, 2.5) == pytest.approx(1 / 6)
    assert full_kelly(0.5, 2.5) != pytest.approx(0.1 / 1.5)


def test_stakes_match_fixture(cases):
    assert len(cases["stakes"]) == 8
    for case in cases["stakes"]:
        got = size_stake(**_stake_kwargs(case))
        assert isinstance(got, Decimal), case["name"]
        assert got == Decimal(case["stake"]), case["name"]
        assert str(got) == case["stake"], case["name"]


def test_exact_whole_cent_not_lost(cases):
    (case,) = [c for c in cases["stakes"] if c["name"] == "exact_whole_cent_not_lost"]
    assert str(size_stake(**_stake_kwargs(case))) == "1.00"


def test_stake_never_negative_when_exposure_exceeds_cap(cases):
    (case,) = [c for c in cases["stakes"] if c["name"] == "exposure_past_cap"]
    got = size_stake(**_stake_kwargs(case))
    assert got == Decimal("0.00")
    assert str(got) == "0.00"
    assert not got.is_signed()


def test_stake_is_keyword_only():
    with pytest.raises(TypeError):
        size_stake(Decimal("0.25"), Decimal("5.5"))  # type: ignore[misc]


@pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.5, float("nan")])
def test_bad_fair_prob_rejected_by_float_helpers(p):
    with pytest.raises(ValueError):
        edge(p, 2.0)
    with pytest.raises(ValueError):
        full_kelly(p, 2.0)


@pytest.mark.parametrize("o", [1.0, 0.5, float("nan"), True, None])
def test_bad_price_rejected_by_float_helpers(o):
    with pytest.raises(ValueError):
        edge(0.5, o)
    with pytest.raises(ValueError):
        full_kelly(0.5, o)


@pytest.mark.parametrize(
    "overrides",
    [
        {"fair_prob": Decimal(0)},
        {"fair_prob": Decimal(1)},
        {"fair_prob": Decimal("-0.1")},
        {"fair_prob": Decimal("1.2")},
        {"fair_prob": Decimal("NaN")},
        {"price": Decimal(1)},
        {"price": Decimal("0.5")},
        {"price": Decimal("Infinity")},
        {"bankroll": Decimal("-0.01")},
        {"participant_exposure": Decimal(-1)},
        {"event_exposure": Decimal(-1)},
        {"fair_prob": 0.25},
        {"price": 5.5},
        {"bankroll": 10000},
    ],
)
def test_bad_inputs_rejected(overrides):
    with pytest.raises(ValueError):
        size_stake(**_valid_kwargs(**overrides))


@pytest.mark.parametrize("field", ["kelly_multiplier", "bet_cap", "participant_cap", "event_cap"])
@pytest.mark.parametrize("value", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN"), 0.02])
def test_bad_caps_rejected(field, value):
    with pytest.raises(ValueError):
        StakeSettings(**{field: value})


def test_cap_bounds_inclusive():
    zero = StakeSettings(bet_cap=Decimal(0))
    assert size_stake(**_valid_kwargs(settings=zero)) == Decimal("0.00")
    one = StakeSettings(
        kelly_multiplier=Decimal(1), bet_cap=Decimal(1), participant_cap=Decimal(1), event_cap=Decimal(1)
    )
    # full Kelly 1/12 of 10000 = 833.333... -> 833.33
    assert str(size_stake(**_valid_kwargs(settings=one))) == "833.33"


def test_value_just_under_a_cent_never_rounds_up():
    # bet cap binds: 0.01 * 0.999...9 (45 nines) = 0.00999...9, which is under one cent. A 40-digit
    # division that rounds half-even would land on 0.01 before the round-down; it must stay 0.00.
    settings = StakeSettings(kelly_multiplier=Decimal(1), bet_cap=Decimal("0.01"))
    got = size_stake(**_valid_kwargs(bankroll=Decimal("0." + "9" * 45), settings=settings))
    assert str(got) == "0.00"


def test_default_settings():
    s = StakeSettings()
    assert (s.kelly_multiplier, s.bet_cap, s.participant_cap, s.event_cap) == (
        Decimal("0.25"),
        Decimal("0.02"),
        Decimal("0.05"),
        Decimal("0.05"),
    )


@pytest.mark.parametrize("o", [float("inf"), float("-inf")])
def test_non_finite_price_rejected_by_float_helpers(o):
    # full_kelly(p, inf) used to return 0.0 (inf / inf is NaN and max(0, NaN) is 0); JS would give NaN.
    with pytest.raises(ValueError):
        edge(0.5, o)
    with pytest.raises(ValueError):
        full_kelly(0.5, o)


def test_implied_still_accepts_infinity_for_golf_parity():
    assert implied(float("inf")) == 0.0
