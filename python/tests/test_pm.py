"""Prediction-market break-even net of taker fees (`pm`).

Every expected value is worked by hand from the venue's published rule (see the FeeModel sources in
`cockpit_core.pm`). Prices are synthetic.

Kalshi (`kalshi-taker-2026-11`): fee = 0.07 * C * P * (1 - P), rounded up to the centicent ($0.0001).
Polymarket (`polymarket-2026-11`): fee = C * 0.05 * p * (1 - p), rounded to 5 dp, a fee below 0.00001
rounding to zero (so rounded down).
"""

import dataclasses
from decimal import ROUND_CEILING, Decimal, Inexact, Rounded, localcontext

import pytest

from cockpit_core import pm
from cockpit_core.pm import FEE_MODELS, FeeModel, pm_break_even

KALSHI = "kalshi-taker-2026-11"
POLYMARKET = "polymarket-2026-11"


# --- Kalshi: 0.07 * C * P * (1 - P), rounded up to $0.0001 ---


def test_kalshi_fee_rounds_up_to_centicent():
    # One contract at $0.50: 0.07 * 1 * 0.50 * 0.50 = 0.0175, already on the $0.0001 grid.
    # Break-even = (0.50 * 1 + 0.0175) / 1 = 0.5175.
    assert pm_break_even(Decimal("0.50"), fee_model=KALSHI) == Decimal("0.5175")
    # One contract at $0.55: 0.07 * 0.55 * 0.45 = 0.017325, rounded UP to 0.0174 (not 0.0173).
    # Break-even = 0.55 + 0.0174 = 0.5674.
    assert pm_break_even(Decimal("0.55"), fee_model=KALSHI) == Decimal("0.5674")


def test_kalshi_fee_is_rounded_per_order_not_per_contract():
    # Three contracts at $0.55: 0.07 * 3 * 0.2475 = 0.051975, rounded up once to 0.0520.
    # (Rounding each contract would give 3 * 0.0174 = 0.0522.) Break-even = (1.65 + 0.052) / 3 = 1.702 / 3.
    got = pm_break_even(Decimal("0.55"), fee_model=KALSHI, contracts=3)
    assert got == Decimal("0." + "5673" + "3" * 36)  # 1.702 / 3 at 40 significant digits, truncated


def test_kalshi_hundred_contracts_at_sixty_cents():
    # 0.07 * 100 * 0.60 * 0.40 = 1.68 exactly. Break-even = (60 + 1.68) / 100 = 0.6168.
    assert pm_break_even(Decimal("0.60"), fee_model=KALSHI, contracts=100) == Decimal("0.6168")


# --- Polymarket: C * 0.05 * p * (1 - p), 5 dp, anything below 0.00001 is zero ---


def test_polymarket_fee_at_fifty_cents():
    # 1 share: 0.05 * 0.25 = 0.0125 -> 0.5125. 100 shares: 1.25 (the published $1.25 at $0.50) -> 0.5125.
    assert pm_break_even(Decimal("0.50"), fee_model=POLYMARKET) == Decimal("0.5125")
    assert pm_break_even(Decimal("0.50"), fee_model=POLYMARKET, contracts=100) == Decimal("0.5125")


def test_polymarket_fee_rounds_down_to_5dp():
    # One share at $0.01: 0.05 * 0.01 * 0.99 = 0.000495 -> 0.00049 (half-up would give 0.00050).
    assert pm_break_even(Decimal("0.01"), fee_model=POLYMARKET) == Decimal("0.01049")


def test_polymarket_fee_below_minimum_is_zero():
    # One share at $0.00015: 0.05 * 0.00015 * 0.99985 = 0.000007498875, below 0.00001, so no fee.
    assert pm_break_even(Decimal("0.00015"), fee_model=POLYMARKET) == Decimal("0.00015")


# --- general behaviour ---


@pytest.mark.parametrize("code", [KALSHI, POLYMARKET])
@pytest.mark.parametrize("price", ["0.05", "0.25", "0.50", "0.75", "0.95"])
@pytest.mark.parametrize("contracts", [1, 7, 100])
def test_break_even_above_price_when_fee_positive(code, price, contracts):
    got = pm_break_even(Decimal(price), fee_model=code, contracts=contracts)
    assert isinstance(got, Decimal)
    assert got > Decimal(price)
    assert got < 1


def test_zero_fee_model_returns_price(monkeypatch):
    # Neither released code is fee-free, so a test-local zero-fee model is registered for this test only.
    zero = FeeModel(code="test-zero-fee", venue="test", taker_rate=Decimal(0), rounding="ceil_cent")
    monkeypatch.setitem(pm._MODELS, zero.code, zero)
    for price in ("0.01", "0.37", "0.5", "0.99"):
        for contracts in (1, 3, 100):
            assert pm_break_even(Decimal(price), fee_model=zero.code, contracts=contracts) == Decimal(price)


def test_ceil_cent_rounding(monkeypatch):
    # A per-cent round-up model (Kalshi's rule for balances held on a $0.01 grid): 0.0175 -> 0.02.
    cent = FeeModel(code="test-cent", venue="test", taker_rate=Decimal("0.07"), rounding="ceil_cent")
    monkeypatch.setitem(pm._MODELS, cent.code, cent)
    assert pm_break_even(Decimal("0.50"), fee_model=cent.code) == Decimal("0.52")


@pytest.mark.parametrize("code", [KALSHI, POLYMARKET])
@pytest.mark.parametrize("price", ["0", "0.0", "1", "1.00", "1.5", "-0.5"])
def test_price_bounds(code, price):
    with pytest.raises(ValueError, match="price"):
        pm_break_even(Decimal(price), fee_model=code)


def test_unknown_model_keyerror():
    with pytest.raises(KeyError, match="no-such-model"):
        pm_break_even(Decimal("0.50"), fee_model="no-such-model")
    with pytest.raises(KeyError):
        pm_break_even(Decimal("0.50"), fee_model="KALSHI-TAKER-2026-11")  # codes are exact, not case-folded


def test_accepts_plain_decimal_strings():
    assert pm_break_even("0.50", fee_model=KALSHI) == Decimal("0.5175")
    assert pm_break_even("0.55", fee_model=KALSHI, contracts=3) == pm_break_even(
        Decimal("0.55"), fee_model=KALSHI, contracts=3
    )


@pytest.mark.parametrize("price", [0.5, 1, None, True, "0.5 ", "+0.5", "5e-1", ".5", "0,5", Decimal("NaN")])
def test_bad_price_types(price):
    with pytest.raises(ValueError, match="price"):
        pm_break_even(price, fee_model=KALSHI)


@pytest.mark.parametrize("contracts", [0, -1, True, False, 1.0, Decimal(1), "1", None, 10**30])
def test_bad_contracts(contracts):
    with pytest.raises(ValueError, match="contracts"):
        pm_break_even(Decimal("0.50"), fee_model=KALSHI, contracts=contracts)


def test_ignores_caller_decimal_context():
    expected = [pm_break_even(Decimal("0.55"), fee_model=c, contracts=3) for c in (KALSHI, POLYMARKET)]
    with localcontext() as ctx:
        ctx.traps[Inexact] = True
        ctx.traps[Rounded] = True
        ctx.rounding = ROUND_CEILING
        ctx.prec = 6
        got = [pm_break_even(Decimal("0.55"), fee_model=c, contracts=3) for c in (KALSHI, POLYMARKET)]
    assert got == expected
    assert [str(g) for g in got] == [str(e) for e in expected]


# --- the registry ---


def test_released_models():
    assert set(FEE_MODELS) == {KALSHI, POLYMARKET}
    for code, model in FEE_MODELS.items():
        assert model.code == code
    assert FEE_MODELS[KALSHI] == FeeModel(KALSHI, "kalshi", Decimal("0.07"), "ceil_centicent")
    assert FEE_MODELS[POLYMARKET] == FeeModel(POLYMARKET, "polymarket", Decimal("0.05"), "floor_5dp")


def test_registry_and_models_are_read_only():
    with pytest.raises(TypeError):
        FEE_MODELS["x"] = FEE_MODELS[KALSHI]  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        FEE_MODELS[KALSHI].taker_rate = Decimal(0)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", ""),
        ("code", 1),
        ("venue", ""),
        ("taker_rate", 0.07),
        ("taker_rate", "0.07"),
        ("taker_rate", Decimal("-0.01")),
        ("taker_rate", Decimal(1)),
        ("taker_rate", Decimal("NaN")),
        ("rounding", "ceil"),
        ("rounding", "half_up_cent"),
    ],
)
def test_fee_model_validation(field, value):
    fields = {"code": "test", "venue": "test", "taker_rate": Decimal("0.05"), "rounding": "ceil_cent"}
    fields[field] = value
    with pytest.raises(ValueError, match=field):
        FeeModel(**fields)
