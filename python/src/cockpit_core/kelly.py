"""Edge, Kelly fraction and capped stake sizing.

`edge` and `full_kelly` are float helpers for research and display. `size_stake` is money: it takes
Decimals, computes exactly with Fractions, divides once at the end and rounds the stake DOWN to cents.
"""

import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from fractions import Fraction

from cockpit_core._exact import exact_money as _exact
from cockpit_core._exact import to_cents
from cockpit_core.odds import implied


def _check_float_prob(fair_prob: float) -> float:
    if (
        isinstance(fair_prob, bool)
        or not isinstance(fair_prob, (int, float))
        or not 0.0 < fair_prob < 1.0  # also rejects NaN
    ):
        raise ValueError(f"fair_prob must be strictly between 0 and 1, got {fair_prob!r}")
    return float(fair_prob)


def edge(fair_prob: float, price: float) -> float:
    """Expected profit per unit staked: p * o - 1. The price must be finite and > 1."""
    p = _check_float_prob(fair_prob)
    implied(price)  # validates the price (> 1, not bool/None/NaN)
    if not math.isfinite(price):  # implied(inf) is 0.0 (kept for golf parity), but an infinite price is no price
        raise ValueError(f"decimal odds must be finite, got {price!r}")
    return p * price - 1.0


def full_kelly(fair_prob: float, price: float) -> float:
    """Full-Kelly fraction of bankroll: max(0, (p * o - 1) / (o - 1))."""
    e = edge(fair_prob, price)
    return max(0.0, e / (price - 1.0))


@dataclass(frozen=True)
class StakeSettings:
    """Fractional-Kelly multiplier and caps, each a fraction of bankroll in [0, 1].

    `event_cap` covers every market of one event together, so mutually exclusive outrights share it.
    """

    kelly_multiplier: Decimal = Decimal("0.25")
    bet_cap: Decimal = Decimal("0.02")
    participant_cap: Decimal = Decimal("0.05")
    event_cap: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        for name in ("kelly_multiplier", "bet_cap", "participant_cap", "event_cap"):
            value = _exact(name, getattr(self, name))
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1], got {getattr(self, name)!r}")


def size_stake(
    *,
    fair_prob: Decimal,
    price: Decimal,
    bankroll: Decimal,
    settings: StakeSettings,
    participant_exposure: Decimal,
    event_exposure: Decimal,
) -> Decimal:
    """Fractional-Kelly stake, capped per bet, per participant and per event, rounded DOWN to cents.

    stake = max(0, min(B*m*(p*o - 1)/(o - 1), B*bet_cap, B*participant_cap - participant_exposure,
                       B*event_cap - event_exposure))

    Computed exactly as one Fraction and divided once, so no cent is lost to early rounding. Exposure
    already past a cap gives 0.00, never a negative stake.
    """
    if not isinstance(settings, StakeSettings):
        raise TypeError(f"settings must be a StakeSettings, got {settings!r}")
    p = _exact("fair_prob", fair_prob)
    o = _exact("price", price)
    b = _exact("bankroll", bankroll)
    participant_used = _exact("participant_exposure", participant_exposure)
    event_used = _exact("event_exposure", event_exposure)
    if not 0 < p < 1:
        raise ValueError(f"fair_prob must be strictly between 0 and 1, got {fair_prob!r}")
    if not o > 1:
        raise ValueError(f"price must be > 1, got {price!r}")
    if b < 0:
        raise ValueError(f"bankroll must be >= 0, got {bankroll!r}")
    if participant_used < 0 or event_used < 0:
        raise ValueError("exposures must be >= 0")

    m = _exact("kelly_multiplier", settings.kelly_multiplier)
    raw = b * m * (p * o - 1) / (o - 1)
    exact = max(
        Fraction(0),
        min(
            raw,
            b * _exact("bet_cap", settings.bet_cap),
            b * _exact("participant_cap", settings.participant_cap) - participant_used,
            b * _exact("event_cap", settings.event_cap) - event_used,
        ),
    )

    # The single division, in a fresh context. It truncates to 40 digits, so it can never lift a value
    # just under a cent boundary up onto it before the final round-down to cents.
    return to_cents(exact, ROUND_DOWN)
