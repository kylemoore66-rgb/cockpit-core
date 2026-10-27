"""Closing line value (no numpy)."""

import math


def clv(bet_odds: float, fair_close_prob: float) -> float:
    """Closing line value: ln(bet odds x fair closing probability)."""
    if not bet_odds > 1.0:
        raise ValueError(f"bet_odds must be > 1, got {bet_odds}")
    if not 0.0 < fair_close_prob < 1.0:
        raise ValueError(f"fair_close_prob must be in (0, 1), got {fair_close_prob}")
    return math.log(bet_odds * fair_close_prob)
