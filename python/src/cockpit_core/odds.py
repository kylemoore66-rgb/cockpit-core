"""Odds basics: implied probability and American/decimal conversion."""

import math
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

from cockpit_core._exact import divide_once, exact_money, shown


class Method(StrEnum):
    MULTIPLICATIVE = "multiplicative"
    POWER = "power"
    SHIN = "shin"


def implied(decimal_odds: float | None) -> float:
    """Raw implied probability (1 / decimal odds, vig included)."""
    if (
        decimal_odds is None
        or isinstance(decimal_odds, bool)
        or not isinstance(decimal_odds, (int, float))
        or not decimal_odds > 1.0  # also rejects NaN
    ):
        raise ValueError(f"decimal odds must be > 1.0, got {decimal_odds!r}")
    return 1.0 / decimal_odds


def decimal_from_american(a: int) -> Decimal:
    """Decimal odds for American odds: +a gives 1 + a/100, -a gives 1 + 100/a.

    Computed exactly as a Fraction and divided once, at precision 40 truncated (ROUND_DOWN), in a fresh
    decimal context whatever the caller's settings. |a| < 100 raises.
    """
    if isinstance(a, bool) or not isinstance(a, int) or abs(a) < 100:
        raise ValueError(f"American odds must be an int with |a| >= 100, got {a!r}")
    exact = 1 + Fraction(a, 100) if a > 0 else 1 + Fraction(100, -a)
    return divide_once(exact)


_PRICE_PLACES = 8
_PRICE_SCALE = 10**_PRICE_PLACES


def price_decimal_from_american(a: int) -> Decimal:
    """The stored decimal price of a bet placed at American odds `a`: the bet-price storage rule.

    +a gives 1 + a/100 and -a gives 1 + 100/a, computed as an exact Fraction and rounded half-up to
    exactly 8 decimal places (so -51200, exactly 1.001953125, stores as 1.00195313). The rounding is done in
    integers, so it is exact and independent of the caller's decimal context. The result always has 8
    places: ``str(price_decimal_from_american(150)) == "2.50000000"``.

    This is the rule the database applies to a stored bet price, and it differs from `decimal_from_american`
    (precision 40, truncated), which is unchanged. Refused with ValueError: anything that is not an int (a
    bool included), |a| < 100, and -100 (the database refuses it; callers normalise -100 to +100).
    """
    if isinstance(a, bool) or not isinstance(a, int) or abs(a) < 100 or a == -100:
        raise ValueError(f"American odds must be an int with |a| >= 100 and not -100, got {shown(a)}")
    exact = 1 + Fraction(a, 100) if a > 0 else 1 + Fraction(100, -a)
    units = math.floor(exact * _PRICE_SCALE + Fraction(1, 2))  # half-up; exact is positive
    whole, frac = divmod(units, _PRICE_SCALE)
    return Decimal(f"{whole}.{frac:0{_PRICE_PLACES}d}")  # the string constructor is exact


def american_from_decimal(o: Decimal) -> int:
    """American odds for decimal odds: o >= 2 gives (o - 1) * 100, o < 2 gives -100 / (o - 1).

    Computed exactly as a Fraction and rounded half away from zero to an int (never round(),
    which is banker's rounding). o <= 1 raises, and so does o >= 1e30 (the shared money limit).
    """
    if isinstance(o, bool) or not isinstance(o, Decimal) or not o.is_finite() or not o > 1:
        raise ValueError(f"decimal odds must be a finite Decimal > 1, got {shown(o)}")
    profit = exact_money("decimal odds", o) - 1
    exact = profit * 100 if o >= 2 else -100 / profit
    magnitude = math.floor(abs(exact) + Fraction(1, 2))
    return -magnitude if exact < 0 else magnitude
