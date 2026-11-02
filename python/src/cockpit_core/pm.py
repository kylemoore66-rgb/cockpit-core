"""Prediction-market break-even net of taker fees: the probability at which buying a binary contract
pays for itself once the venue's fee is counted.

A contract bought at price p (dollars, 0 < p < 1) pays $1 if it wins. Buying C contracts costs p*C plus
the taker fee, so the trade breaks even when the win probability is (p*C + fee) / C. Both venues modelled
here publish a fee of the form rate * C * p * (1 - p), each with its own rounding (see `FeeModel`).

Fee models are versioned: a code names one published schedule, read on a stated date, and never changes
once released. When a venue changes its fees, a new code is added and the old one is kept, so a number
computed under an old code can always be recomputed.

Money math, like `expected`: the fee is computed and rounded exactly with Fractions, and the break-even is
divided once, at precision 40 truncated (ROUND_DOWN), whatever the caller's decimal context. The result is
NOT rounded: round for display only. `price` is a Decimal or a plain decimal string
(``^[0-9]+(\\.[0-9]+)?$``) inside the shared money domain.
"""

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from cockpit_core._exact import MONEY_EXPONENT_LIMIT, divide_once, exact_money, shown

__all__ = ["FEE_MODELS", "FeeModel", "pm_break_even"]

_PLAIN = re.compile(r"[0-9]+(?:\.[0-9]+)?")  # ASCII digits only; used with fullmatch, so no trailing newline
_MAX_CONTRACTS = 10**MONEY_EXPONENT_LIMIT  # exclusive

# rounding name -> (grid step in dollars, which way a fee off the grid goes)
_ROUNDINGS: dict[str, tuple[Fraction, Callable[[Fraction], int]]] = {
    "ceil_cent": (Fraction(1, 100), math.ceil),  # up to the next $0.01
    "ceil_centicent": (Fraction(1, 10_000), math.ceil),  # up to the next $0.0001
    "floor_5dp": (Fraction(1, 100_000), math.floor),  # down to 0.00001
}


@dataclass(frozen=True)
class FeeModel:
    """One venue's published taker fee: fee = taker_rate * C * p * (1 - p), rounded per `rounding`.

    C is the number of contracts in the order and p the price in dollars; the fee is computed and rounded
    once, on the whole quantity. That matches Kalshi, whose rounding-fee accumulator makes an order's fills
    converge to one fill's fee. Polymarket applies fees at match time, so for it this holds only for one
    order filled at one price in one match. `rounding` is one of:

    - ``"ceil_cent"``: rounded up to the next $0.01.
    - ``"ceil_centicent"``: rounded up to the next $0.0001.
    - ``"floor_5dp"``: rounded down to 5 decimal places (0.00001).

    `code` and `venue` are non-empty strings and `taker_rate` a finite Decimal with 0 <= rate < 1;
    anything else raises ValueError.
    """

    code: str
    venue: str
    taker_rate: Decimal
    rounding: str

    def __post_init__(self) -> None:
        for name in ("code", "venue"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string, got {shown(value)}")
        rate = exact_money("taker_rate", self.taker_rate)
        if not 0 <= rate < 1:
            raise ValueError(f"taker_rate must be >= 0 and < 1, got {shown(self.taker_rate)}")
        if not isinstance(self.rounding, str) or self.rounding not in _ROUNDINGS:
            raise ValueError(f"rounding must be one of {sorted(_ROUNDINGS)}, got {shown(self.rounding)}")


# Kalshi, checked 2026-11-02.
# Sources:
# - Fee schedule, https://kalshi.com/docs/kalshi-fee-schedule.pdf, linked from https://kalshi.com/fee-schedule:
#   NOT read directly. Both returned HTTP 429 (a bot checkpoint) on 2026-11-02. A search index's copy of the
#   PDF gives the title and date "July 2026 - 7.7.26 Update" and the formula
#   "fees = round up(M x 0.07 x C x P x (1-P))" (C contracts, P the price in dollars, M a per-market
#   multiplier, default 1); another indexed copy is dated Feb 5, 2026. That title, date and wording are
#   unverified.
# - Fee rounding, https://docs.kalshi.com/getting_started/fee_rounding, read directly on 2026-11-02. Its
#   worked example's model fee of $0.00363825 on a $0.055 buy equals 0.07 x 0.055 x 0.945 exactly. It says
#   "Direct member balances are aligned to `$0.0001` (`0.01c`)" and "Non-direct member balances are aligned
#   to `$0.01` (`1c`)" (FCM-cleared members); the trade fee is "rounded up to the nearest `$0.000001`" and a
#   rounding fee brings the balance back to the member's grid; "The fee accumulator applies across all fills
#   of an order so that the total fee converges to what a single equivalent fill would cost."
# - Fees, https://help.kalshi.com/trading/fees (read directly): "Some markets have fees that are different
#   from those of other markets"; maker fees apply only to resting orders.
# So the rate 0.07 and the price term P(1 - P) are corroborated by the fee-rounding page's worked example,
# and the round-up to $0.0001 is derived from its direct-member balance grid (fee rounded up to $0.000001,
# then the rounding fee restores the $0.0001 grid; with p*C on that grid the net is a fee rounded up to
# $0.0001). Neither the rate, the price term nor the round-up was read from the schedule itself.
# Scope: the general taker fee (M = 1) for a direct member (an account held with Kalshi itself), one order
# at one price. Not modelled: markets with a different multiplier, maker fees, and accounts cleared through
# an FCM (their balances sit on the $0.01 grid, so their fee rounds up to the cent).
_KALSHI_TAKER_2026_11 = FeeModel(
    code="kalshi-taker-2026-11",
    venue="kalshi",
    taker_rate=Decimal("0.07"),
    rounding="ceil_centicent",
)

# Polymarket, read 2026-11-02.
# Source: Fees, https://docs.polymarket.com/trading/fees (read directly). "fee = C x feeRate x p x (1 - p)",
# "Where C = number of shares traded and p = price of the shares"; "Makers are never charged fees. Only
# takers pay fees."; "Taker fees are calculated in USDC". Fee Precision: "Fees are rounded to 5 decimal
# places. The smallest fee charged is 0.00001 USDC. Anything smaller rounds to zero". The page does not name
# the rounding direction; rounding down is the only rule under which every fee below 0.00001 rounds to zero.
# Taker fee rate by category: Crypto 0.07; Sports, Economics, Culture, Weather, Other / General and Combos
# 0.05; Finance, Politics, Mentions and Tech 0.04; Geopolitics 0 ("Geopolitical and world events markets
# are fee-free").
# Scope: the Other / General taker rate, 0.05, which Sports, Economics, Culture, Weather and Combos share.
# Not modelled: Crypto (0.07), Finance, Politics, Mentions and Tech (0.04), and fee-free Geopolitics, nor
# the maker and taker rebate programmes. USDC is taken as dollars. Polymarket applies fees at match time, so
# one rounding per order holds only for one order filled at one price in one match. The page does not say how
# a buy's fee is collected; this model assumes it is paid in USDC on top of price * contracts.
_POLYMARKET_2026_11 = FeeModel(
    code="polymarket-2026-11",
    venue="polymarket",
    taker_rate=Decimal("0.05"),
    rounding="floor_5dp",
)

_MODELS: dict[str, FeeModel] = {m.code: m for m in (_KALSHI_TAKER_2026_11, _POLYMARKET_2026_11)}

FEE_MODELS: Mapping[str, FeeModel] = MappingProxyType(_MODELS)
"""Released fee models by code (read-only). Codes are immutable: a fee change adds a new code."""


def _price(price: Any) -> Fraction:
    if isinstance(price, str):
        if _PLAIN.fullmatch(price) is None:
            raise ValueError(f"price must be a Decimal or a plain non-negative decimal string, got {shown(price)}")
        price = Decimal(price)  # exact: the string constructor never rounds, and the grammar has no exponent
    p = exact_money("price", price)
    if not 0 < p < 1:
        raise ValueError(f"price must be > 0 and < 1, got {shown(price)}")
    return p


def _contracts(contracts: Any) -> int:
    if isinstance(contracts, bool) or not isinstance(contracts, int) or not 1 <= contracts < _MAX_CONTRACTS:
        raise ValueError(f"contracts must be an int >= 1 and < 1e{MONEY_EXPONENT_LIMIT}, got {shown(contracts)}")
    return contracts


def _fee(model: FeeModel, p: Fraction, contracts: int) -> Fraction:
    """The model's fee on one order of `contracts` at `p`, rounded onto its grid, exactly."""
    step, direction = _ROUNDINGS[model.rounding]
    raw = Fraction(model.taker_rate) * contracts * p * (1 - p)
    return direction(raw / step) * step


def pm_break_even(price: Decimal | str, *, fee_model: str, contracts: int = 1) -> Decimal:
    """Break-even win probability of buying `contracts` at `price` after the taker fee: (p*C + fee) / C.

    `fee_model` is a code in `FEE_MODELS` (an unknown code raises KeyError). `price` is in dollars with
    0 < price < 1, and `contracts` an int of at least 1; the fee is rounded once on the whole order, so
    rounding is per order, not per contract. Exact, divided once (precision 40, truncated), not rounded.
    One contract at $0.50 under ``kalshi-taker-2026-11`` breaks even at 0.5175 (a fee of $0.0175).

    Assumptions, not checked: the fee is paid in dollars (USDC) on top of price * contracts, which is what
    (p*C + fee) / C assumes. One rounding per order holds for Kalshi (its fee accumulator converges an
    order's fills); for Polymarket, which applies fees at match time, only for one order filled at one price
    in one match. `price` is on the venue's tick: the ``ceil_centicent`` rule matches Kalshi's rounding only
    when p*C is on the $0.0001 grid, and an off-tick price can give a result above 1 (``"0.99995"`` under
    ``kalshi-taker-2026-11`` gives 1.00005).
    """
    try:
        model = FEE_MODELS[fee_model]
    except (KeyError, TypeError):
        raise KeyError(f"unknown fee model {shown(fee_model)}") from None
    p = _price(price)
    c = _contracts(contracts)
    return divide_once(p + _fee(model, p, c) / c)
