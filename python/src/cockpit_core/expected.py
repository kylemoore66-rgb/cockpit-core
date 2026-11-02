"""Expected profit, profit variance and the cumulative band: what a bettor should have made, and how far
from it luck alone can take him.

For a stake b at decimal price o with fair win probability p, profit is b(o - 1) with probability p and -b
otherwise, so the expected profit is b(p*o - 1) and the variance b^2 * o^2 * p(1 - p). `outcome_moments`
generalises this to any list of settled outcomes (pushes, half wins, dead heats), each with its probability.
`cumulative_band` runs a sequence of bets into the band a Results screen draws: the running total of
expected profit, and the standard deviation of the running total (independent bets, so variances add).

Money math, like `settle.profit`: inputs are computed exactly with Fractions and each result is divided
once, at precision 40 truncated (ROUND_DOWN), in a fresh decimal context whatever the caller's settings.
Results are NOT rounded to cents: round for display only. Serialise with `str` or format them; compare by
value. `expected_profit`, `profit_variance` and `outcome_moments` take Decimals or plain decimal strings
(``^[0-9]+(\\.[0-9]+)?$``, as in the TS package), inside the shared money domain (|x| < 1e30, no non-zero
value below 1e-60).
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import MAX_PREC, Decimal, localcontext
from fractions import Fraction
from typing import Any

from cockpit_core._exact import divide_once, exact_money, fresh_context, shown
from cockpit_core.settle import Settlement

__all__ = ["BandPoint", "cumulative_band", "expected_profit", "outcome_moments", "profit_variance"]

_PLAIN = re.compile(r"[0-9]+(?:\.[0-9]+)?")  # ASCII digits only; used with fullmatch, so no trailing newline


def _exact(name: str, value: Any) -> Fraction:
    """A Decimal or a plain non-negative decimal string, as an exact Fraction inside the money domain."""
    if isinstance(value, str):
        if _PLAIN.fullmatch(value) is None:
            raise ValueError(f"{name} must be a Decimal or a plain non-negative decimal string, got {shown(value)}")
        value = Decimal(value)  # exact: the string constructor never rounds, and the grammar has no exponent
    return exact_money(name, value)


def _stake(stake: Any) -> Fraction:
    b = _exact("stake", stake)
    if b < 0:
        raise ValueError(f"stake must be >= 0, got {shown(stake)}")
    return b


def _price(price: Any) -> Fraction:
    o = _exact("price", price)
    if not o > 1:
        raise ValueError(f"price must be > 1, got {shown(price)}")
    return o


def _probability(name: str, value: Any) -> Fraction:
    p = _exact(name, value)
    if not 0 <= p <= 1:
        raise ValueError(f"{name} must be between 0 and 1, got {shown(value)}")
    return p


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def expected_profit(stake: Decimal | str, fair_prob: Decimal | str, price: Decimal | str) -> Decimal:
    """Expected profit of a win/lose bet: stake * (p * o - 1), exact, divided once (precision 40), not rounded.

    Needs stake >= 0, 0 <= fair_prob <= 1 and price > 1. Stake 100 at 1.9091 with p = 0.55 is exactly 5.0005.
    """
    b = _stake(stake)
    p = _probability("fair_prob", fair_prob)
    o = _price(price)
    return divide_once(b * (p * o - 1))


def profit_variance(stake: Decimal | str, fair_prob: Decimal | str, price: Decimal | str) -> Decimal:
    """Variance of a win/lose bet's profit: stake^2 * o^2 * p(1 - p), exact, divided once (precision 40).

    The same inputs and checks as `expected_profit`. Equal to `outcome_moments` over WIN with p and LOSS
    with 1 - p.
    """
    b = _stake(stake)
    p = _probability("fair_prob", fair_prob)
    o = _price(price)
    return divide_once(b * b * o * o * p * (1 - p))


def outcome_moments(
    stake: Decimal | str,
    price: Decimal | str,
    outcomes: Sequence[tuple[Decimal | str, Settlement]],
) -> tuple[Decimal, Decimal]:
    """(mean, variance) of a bet's profit over settled outcomes, each a (probability, Settlement) pair.

    An outcome settled s pays stake * (s.win * o + s.refund - 1), as `settle.profit` does before rounding.
    The probabilities must each be in [0, 1] and sum to exactly 1 (an exact check, no tolerance), so an
    empty list is rejected. Both moments are exact and divided once (precision 40), not rounded. A settlement
    that is not a `Settlement` is a TypeError, as in `settle.profit`; every other bad input is a ValueError.
    """
    b = _stake(stake)
    o = _price(price)
    if not _is_sequence(outcomes):
        raise ValueError(f"outcomes must be a sequence of (probability, Settlement) pairs, got {shown(outcomes)}")
    weighted: list[tuple[Fraction, Fraction]] = []
    for item in outcomes:
        if not _is_sequence(item) or len(item) != 2:
            raise ValueError(f"outcomes must be (probability, Settlement) pairs, got {shown(item)}")
        q, s = item
        if not isinstance(s, Settlement):
            raise TypeError(f"each outcome's settlement must be a Settlement, got {shown(s)}")
        weighted.append((_probability("outcome probability", q), b * (s.win * o + s.refund - 1)))
    total = sum((q for q, _ in weighted), Fraction(0))
    if total != 1:
        raise ValueError(f"outcome probabilities must sum to exactly 1, got {total}")
    mean = sum((q * x for q, x in weighted), Fraction(0))
    variance = sum((q * (x - mean) ** 2 for q, x in weighted), Fraction(0))
    return divide_once(mean), divide_once(variance)


@dataclass(frozen=True)
class BandPoint:
    """One point of the cumulative band: the running total of expected profit, and its standard deviation."""

    expected: Decimal
    sigma: float


def cumulative_band(bets: Sequence[tuple[Decimal, Decimal]]) -> list[BandPoint]:
    """The band after each bet: running sum of expected profit, and sqrt of the running sum of variance.

    `bets` holds (expected, variance) Decimal pairs, for example from `expected_profit` and
    `profit_variance` (or `outcome_moments`), one per bet in order; the bets are taken as independent, so
    variances add. Each value must be a finite Decimal inside the money domain (strings are not accepted:
    an expected profit is often negative), and a variance must be >= 0; anything else is a ValueError.

    The running sum of expected profit is exact (no precision limit), so it is the same in every language.
    `sigma` is ``math.sqrt(float(running variance))``: a float for drawing, correctly rounded at each step,
    so the TS package's ``Math.sqrt(Number(...))`` gives the same double. A zero is never negative zero.
    """
    if not _is_sequence(bets):
        raise ValueError(f"bets must be a sequence of (expected, variance) Decimal pairs, got {shown(bets)}")
    checked: list[tuple[Decimal, Decimal]] = []
    for item in bets:
        if not _is_sequence(item) or len(item) != 2:
            raise ValueError(f"bets must be (expected, variance) Decimal pairs, got {shown(item)}")
        expected, variance = item
        exact_money("expected", expected)
        if exact_money("variance", variance) < 0:
            raise ValueError(f"variance must be >= 0, got {shown(variance)}")
        checked.append((expected, variance))

    points: list[BandPoint] = []
    total_expected = total_variance = Decimal(0)
    # Decimal addition is exact when the precision cannot run out, and it only ever produces as many digits
    # as the inputs span, so the maximum precision costs nothing.
    with localcontext(fresh_context(MAX_PREC)):
        for expected, variance in checked:
            total_expected += expected
            total_variance += variance
            point_expected = total_expected if total_expected else Decimal(0)  # no "-0"
            point_variance = total_variance if total_variance else Decimal(0)
            points.append(BandPoint(expected=point_expected, sigma=math.sqrt(float(point_variance))))
    return points
