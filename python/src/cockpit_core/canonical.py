# ruff: noqa: TRY004 (contract: every non-canonical input raises ValueError, never TypeError)
"""Canonical bytes for predictions: the exact bytes that get hashed and published.

One byte of drift breaks every proof, so the rules are strict:

* Probabilities are strings at 6 decimal places and prices at 4, both rounded half-up.
  Floats go through ``Decimal(repr(x))``, never ``Decimal(x)``, so 0.1234565 is
  0.1234565 and not its binary expansion.
* Timestamps are UTC with exactly millisecond precision: ``YYYY-MM-DDTHH:MM:SS.mmmZ``.
  Anything finer is rejected (a JavaScript ``Date`` could not reproduce it).
  Publishers call :func:`to_canonical_time` first, which truncates.
* Every string is Unicode NFC, and ``features_summary`` is a str-to-str mapping.
* The 10 fields are serialised with RFC 8785 (JSON Canonicalization Scheme). Every
  value is a string or a flat string mapping, so the output equals sorted-key compact
  JSON with raw UTF-8.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

import rfc8785

_PROB_QUANTUM = Decimal("0.000001")
_PRICE_QUANTUM = Decimal("0.0001")
_ZERO = Decimal(0)
_ONE = Decimal(1)


def _to_decimal(value: object, what: str) -> Decimal:
    """Exact Decimal for a float (via repr), Decimal or str. Rejects bool, NaN, infinity."""
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a number, not bool")
    try:
        if isinstance(value, float):
            d = Decimal(repr(float(value)))  # float(): numpy/pandas float64 subclasses repr as "np.float64(..)"
        elif isinstance(value, Decimal):
            d = value
        elif isinstance(value, str):
            d = Decimal(value)
        else:
            raise ValueError(f"{what} must be float, Decimal or str, got {type(value).__name__}")
    except InvalidOperation:
        raise ValueError(f"{what} is not a number: {value!r}") from None
    if not d.is_finite():
        raise ValueError(f"{what} must be finite: {value!r}")
    return d


def _quantize(d: Decimal, quantum: Decimal, what: str) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        try:
            return d.quantize(quantum, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise ValueError(f"{what} out of range: {d}") from None


def fmt_prob(p: float | Decimal | str) -> str:
    """Probability as a 6 dp half-up string. Must lie strictly between 0 and 1 after rounding."""
    d = _to_decimal(p, "probability")
    q = _quantize(d, _PROB_QUANTUM, "probability")
    if not _ZERO < q < _ONE:
        raise ValueError(f"probability must be strictly between 0 and 1 at 6 dp, got {p!r}")
    return f"{q:f}"


def fmt_price(o: float | Decimal | str) -> str:
    """Decimal odds as a 4 dp half-up string. Must be greater than 1 after rounding."""
    d = _to_decimal(o, "price")
    q = _quantize(d, _PRICE_QUANTUM, "price")
    if not q > _ONE:
        raise ValueError(f"price must be greater than 1 at 4 dp, got {o!r}")
    return f"{q:f}"


def _require_aware_utc(dt: datetime) -> None:
    if not isinstance(dt, datetime):
        raise ValueError(f"timestamp must be a datetime, got {type(dt).__name__}")
    offset = dt.utcoffset()
    if offset is None:
        raise ValueError("timestamp must be timezone-aware (naive datetime rejected)")
    if offset != timedelta(0):
        raise ValueError(f"timestamp must be UTC, got offset {offset}")


def fmt_ts(dt: datetime) -> str:
    """UTC timestamp as ``YYYY-MM-DDTHH:MM:SS.mmmZ``. Rejects naive, non-UTC and sub-millisecond values."""
    _require_aware_utc(dt)
    # pandas.Timestamp keeps nanoseconds outside .microsecond; they must not be dropped silently
    nanosecond = getattr(dt, "nanosecond", 0)
    if dt.microsecond % 1000 != 0 or nanosecond != 0:
        raise ValueError(
            f"timestamp has sub-millisecond precision ({dt.microsecond} us, {nanosecond} ns); use to_canonical_time first"
        )
    return (
        f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}T"
        f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{dt.microsecond // 1000:03d}Z"
    )


def to_canonical_time(dt: datetime) -> datetime:
    """Convert an aware datetime to UTC and truncate (not round) to the millisecond."""
    if not isinstance(dt, datetime):
        raise ValueError(f"timestamp must be a datetime, got {type(dt).__name__}")
    if dt.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware (naive datetime rejected)")
    utc = dt.astimezone(UTC)
    # rebuild as a plain datetime: drops any subclass-only nanosecond field along with sub-ms digits
    return datetime(
        utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second, utc.microsecond // 1000 * 1000, tzinfo=UTC
    )


def _nfc(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{what} must be a str, got {type(value).__name__}")
    if not unicodedata.is_normalized("NFC", value):
        raise ValueError(f"{what} is not Unicode NFC: {value!r}")
    return value


@dataclass(frozen=True)
class CanonicalPrediction:
    model_version: str
    sport: str
    event: str
    market: str
    selection: str
    fair_prob: float | Decimal
    paper_price: Decimal | str
    paper_book: str
    predicted_at: datetime
    features_summary: Mapping[str, str]


def canonical_bytes(p: CanonicalPrediction) -> bytes:
    """RFC 8785 bytes of the 10 canonical fields. Raises ValueError on anything non-canonical."""
    if not isinstance(p.features_summary, Mapping):
        raise ValueError("features_summary must be a mapping of str to str")
    features = {
        _nfc(k, "features_summary key"): _nfc(v, f"features_summary[{k!r}]") for k, v in p.features_summary.items()
    }
    obj = {
        "model_version": _nfc(p.model_version, "model_version"),
        "sport": _nfc(p.sport, "sport"),
        "event": _nfc(p.event, "event"),
        "market": _nfc(p.market, "market"),
        "selection": _nfc(p.selection, "selection"),
        "fair_prob": fmt_prob(p.fair_prob),
        "paper_price": fmt_price(p.paper_price),
        "paper_book": _nfc(p.paper_book, "paper_book"),
        "predicted_at": fmt_ts(p.predicted_at),
        "features_summary": features,
    }
    return rfc8785.dumps(obj)
