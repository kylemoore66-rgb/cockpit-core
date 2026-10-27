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

# Shared domain limits (the TS package enforces the same ones, asserted by the `domain_limits` fixtures).
MONEY_EXPONENT_LIMIT = 30  # a money input must satisfy |x| < 1e30, i.e. a leading digit below 10**30
MAX_EXPONENT = 60  # no non-zero input may have its leading digit beyond 10**60 or below 10**-60
_SHOWN_CHARS = 40


def shown(value: object) -> str:
    """``repr(value)`` cut to about 40 characters, so a hostile value cannot blow up an error message."""
    text = repr(value)
    return text if len(text) <= _SHOWN_CHARS else text[:_SHOWN_CHARS] + "..."


def check_exponent(name: str, d: Decimal) -> None:
    """Reject a finite non-zero Decimal whose leading digit lies beyond 10**60 or below 10**-60.

    Reads only the exponent (``adjusted()``), never the digits, so ``1e-100000000`` fails at once instead
    of expanding to a 100-million-digit integer. Zero is zero whatever its exponent.
    """
    if d and not -MAX_EXPONENT <= d.adjusted() <= MAX_EXPONENT:
        raise ValueError(f"{name} is out of range (decimal exponent beyond +/-{MAX_EXPONENT}), got {shown(d)}")


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
    """Exact Fraction of a finite Decimal inside the money domain; anything else raises ValueError.

    Rejected: non-Decimals (float, int, bool, None), NaN and infinities, ``|value| >= 1e30``, and a
    non-zero value below ``1e-60`` in magnitude. The bounds are checked on the exponent alone, before the
    digits are expanded into a Fraction.
    """
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal, got {shown(value)}")
    if value and value.adjusted() >= MONEY_EXPONENT_LIMIT:
        raise ValueError(f"{name} must be less than 1e{MONEY_EXPONENT_LIMIT} in magnitude, got {shown(value)}")
    check_exponent(name, value)
    return Fraction(value)  # exact and context-free


def divide_once(exact: Fraction, precision: int = DIVISION_PRECISION) -> Decimal:
    """The single division: numerator / denominator at `precision` (default 40), truncated (ROUND_DOWN).

    Truncation never moves a value across a cent or half-cent boundary: a value at or past a boundary
    stays at or past it, and a value short of one only gets shorter.
    """
    with localcontext(fresh_context(precision, ROUND_DOWN)):
        return Decimal(exact.numerator) / Decimal(exact.denominator)


def to_cents(exact: Fraction, rounding: str) -> Decimal:
    """`exact` divided once (see divide_once) and rounded to cents with `rounding`.

    The division runs at precision 40, widened only when the integer part has more than 36 digits (which the
    1e30 money limit allows for a profit, up to 60 digits), so every cent and half-cent boundary is still a
    representable value and the truncation argument holds. Below 1e36 the result is exactly what precision
    40 gives.
    """
    integer_digits = len(str(abs(exact.numerator) // exact.denominator))
    precision = max(DIVISION_PRECISION, integer_digits + 4)
    with localcontext(fresh_context(precision, ROUND_DOWN)):
        return divide_once(exact, precision).quantize(CENT, rounding=rounding)
