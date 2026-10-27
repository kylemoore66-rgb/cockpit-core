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
