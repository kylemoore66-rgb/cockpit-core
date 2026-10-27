"""Private helpers for exact money arithmetic, independent of the caller's decimal context.

Every Decimal operation here runs in a fresh context built from explicit values, so a caller who has
set traps (for example Inexact), a different rounding mode or a low precision gets the same result as
everyone else, and never a decimal signal instead of a ValueError.
"""

from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from fractions import Fraction

CENT = Decimal("0.01")
DIVISION_PRECISION = 40


def fresh_context(prec: int, rounding: str = ROUND_HALF_EVEN) -> Context:
    """A context with the stdlib default settings except `prec` and `rounding`; nothing is inherited."""
    return Context(
        prec=prec,
        rounding=rounding,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


def exact_money(name: str, value: object) -> Fraction:
    """Exact Fraction of a finite Decimal; anything else (float, int, bool, None, NaN, inf) raises ValueError."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal, got {value!r}")
    return Fraction(value)  # exact and context-free


def divide_once(exact: Fraction) -> Decimal:
    """The single division: numerator / denominator at precision 40, truncated (ROUND_DOWN).

    Truncation never moves a value across a cent or half-cent boundary: a value at or past a boundary
    stays at or past it, and a value short of one only gets shorter.
    """
    with localcontext(fresh_context(DIVISION_PRECISION, ROUND_DOWN)):
        return Decimal(exact.numerator) / Decimal(exact.denominator)


def to_cents(exact: Fraction, rounding: str) -> Decimal:
    """`exact` divided once (see divide_once) and rounded to cents with `rounding`."""
    with localcontext(fresh_context(DIVISION_PRECISION, ROUND_DOWN)):
        return divide_once(exact).quantize(CENT, rounding=rounding)
