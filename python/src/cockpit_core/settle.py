"""Settlement: a bet's (win, refund) fractions, dead heats, matchup tie rules and profit.

A settled bet pays back `win` of the stake at the price and `refund` of the stake at evens, and loses
the rest, so profit per unit staked is w * o + r - 1. A full win is (1, 0), a loss (0, 0), a void
(0, 1), a half win (1/2, 1/2), a half loss (0, 1/2), and a dead heat for `places_paid` places among
`tied` players is (places_paid / tied, 0).

`profit` is money: Decimal in and out, computed exactly with Fractions, divided once, and rounded
half-up (away from zero) to cents. `unit_profit` is the float helper for research.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from fractions import Fraction
from numbers import Integral, Rational
from typing import Any

from cockpit_core.odds import implied

_CENT = Decimal("0.01")


class TieRule(StrEnum):
    VOID = "void"
    DEAD_HEAT = "dead_heat"
    LOSES = "loses"


# Normalised book wording -> rule.
_TIE_TEXT: dict[str, TieRule] = {
    "void": TieRule.VOID,
    "separate bet offered": TieRule.LOSES,
}


def tie_rule_from_text(s: str) -> TieRule:
    """Map a book's tie-rule wording to a TieRule. Unknown wording or a non-string raises."""
    if not isinstance(s, str):
        raise ValueError(f"tie rule text must be a string, got {s!r}")  # noqa: TRY004 (contract: ValueError)
    key = " ".join(s.lower().split())
    try:
        return _TIE_TEXT[key]
    except KeyError:
        raise ValueError(f"unknown tie rule text: {s!r}") from None


def _exact_fraction(name: str, value: Any) -> Fraction:
    """An exact rational (int or Fraction, not bool) as a Fraction. Floats, Decimals, None, NaN raise."""
    if isinstance(value, bool) or not isinstance(value, Rational):
        raise ValueError(f"{name} must be an exact int or Fraction, got {value!r}")  # noqa: TRY004 (contract: ValueError)
    return Fraction(value)


@dataclass(frozen=True)
class Settlement:
    """Fractions of the stake paid at the price (`win`) and returned at evens (`refund`).

    Both are exact Fractions with 0 <= win, 0 <= refund and win + refund <= 1.
    """

    win: Fraction
    refund: Fraction

    def __post_init__(self) -> None:
        win = _exact_fraction("win", self.win)
        refund = _exact_fraction("refund", self.refund)
        if win < 0 or refund < 0 or win + refund > 1:
            raise ValueError(f"need 0 <= win, 0 <= refund, win + refund <= 1; got win={win}, refund={refund}")
        object.__setattr__(self, "win", win)
        object.__setattr__(self, "refund", refund)


WIN = Settlement(Fraction(1), Fraction(0))
LOSS = Settlement(Fraction(0), Fraction(0))
VOID = Settlement(Fraction(0), Fraction(1))
HALF_WIN = Settlement(Fraction(1, 2), Fraction(1, 2))
HALF_LOSS = Settlement(Fraction(0), Fraction(1, 2))


def _check_count(name: str, n: Any) -> int:
    if isinstance(n, bool) or not isinstance(n, Integral) or n < 1:
        raise ValueError(f"{name} must be an integer >= 1, got {n!r}")
    return int(n)


def dead_heat(places_paid: int, tied: int) -> Settlement:
    """Dead heat: `tied` players share the last `places_paid` paying places, so places_paid / tied wins.

    Needs 1 <= places_paid <= tied.
    """
    places = _check_count("places_paid", places_paid)
    k = _check_count("tied", tied)
    if places > k:
        raise ValueError(f"places_paid ({places}) cannot exceed tied ({k})")
    return Settlement(Fraction(places, k), Fraction(0))


def _check_rank(r: Any) -> int:
    """An integral rank >= 1 (Python or numpy int). NaN, masked, floats and bools raise."""
    if isinstance(r, bool) or not isinstance(r, Integral) or r < 1:
        raise ValueError(f"matchup rank must be None or an integer >= 1, got {r!r}")
    return int(r)


def matchup_settlement(ranks: Sequence[int | None], pick: int, rule: TieRule | str) -> Settlement:
    """Settlement of a 2-ball or 3-ball pick.

    ranks are within-group ranks (lowest is best, ties share a rank, None = withdrawn or disqualified).
    Any None voids the bet. A pick beaten by anyone loses; a unique best wins. A tie for best rank
    among k players settles by the tie rule: VOID voids, DEAD_HEAT pays 1/k, LOSES loses. Any other
    non-integer rank (NaN, numpy masked, a float, a bool) or a rank below 1 raises.

    `rule` may be a TieRule or its plain string value (as read back from JSON or a database); any
    other value raises, even when the bet has no tie, so a bad rule never settles silently.
    """
    try:
        rule = TieRule(rule)
    except ValueError:
        raise ValueError(f"unknown tie rule: {rule!r}") from None
    if not 2 <= len(ranks) <= 3:
        raise ValueError(f"matchup needs 2 or 3 players, got {len(ranks)}")
    if not 0 <= pick < len(ranks):
        raise ValueError(f"pick {pick} out of range for {len(ranks)} players")
    checked = [None if r is None else _check_rank(r) for r in ranks]
    if any(r is None for r in checked):
        return VOID
    valid: list[int] = [r for r in checked if r is not None]
    best = min(valid)
    if valid[pick] > best:
        return LOSS
    k = sum(1 for r in valid if r == best)
    if k == 1:
        return WIN
    if rule is TieRule.VOID:
        return VOID
    if rule is TieRule.DEAD_HEAT:
        return dead_heat(1, k)
    if rule is TieRule.LOSES:
        return LOSS
    raise ValueError(f"unhandled tie rule: {rule!r}")  # unreachable: every TieRule is handled above


def _exact_money(name: str, value: Decimal) -> Fraction:
    """Exact Fraction of a finite Decimal; anything else (float, int, bool, NaN, inf) raises."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal, got {value!r}")
    return Fraction(str(value))


def _check_settlement(s: Settlement) -> None:
    if not isinstance(s, Settlement):
        raise TypeError(f"s must be a Settlement, got {s!r}")


def profit(stake: Decimal, price: Decimal, s: Settlement) -> Decimal:
    """Profit in money: stake * (w * o + r - 1), exact, rounded half-up (away from zero) to cents.

    The win fraction is never turned into a decimal before multiplying: stake 11 at 2.25 with
    win 1/6 is exactly -6.875 and settles at -6.88.
    """
    _check_settlement(s)
    b = _exact_money("stake", stake)
    o = _exact_money("price", price)
    if b < 0:
        raise ValueError(f"stake must be >= 0, got {stake!r}")
    if not o > 1:
        raise ValueError(f"price must be > 1, got {price!r}")

    exact = b * (s.win * o + s.refund - 1)

    # The single division. ROUND_DOWN (toward zero) at precision 40 never moves a value across a
    # half-cent boundary: a value at or past a boundary stays at or past it (the boundary itself has
    # few digits, so truncation stops on it at worst), and a value short of one only gets shorter.
    # So the final half-up rounding sees the same side of every boundary as the exact value does.
    with localcontext() as ctx:
        ctx.prec = 40
        ctx.rounding = ROUND_DOWN
        value = Decimal(exact.numerator) / Decimal(exact.denominator)
        cents = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    return cents if cents != 0 else Decimal("0.00")  # no "-0.00"


def unit_profit(price: float, s: Settlement) -> float:
    """Profit per unit staked, w * o + r - 1, as a float (research use).

    Computed exactly from the float price and rounded to a float once.
    """
    _check_settlement(s)
    implied(price)  # validates the price (> 1, not bool/None/NaN)
    if not math.isfinite(price):
        raise ValueError(f"decimal odds must be finite, got {price!r}")
    return float(s.win * Fraction(price) + s.refund - 1)
