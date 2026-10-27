import hashlib
import json
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import rfc8785

from cockpit_core.canonical import (
    CanonicalPrediction,
    canonical_bytes,
    fmt_price,
    fmt_prob,
    fmt_ts,
    to_canonical_time,
)


def _build(pred: dict) -> CanonicalPrediction:
    return CanonicalPrediction(
        model_version=pred["model_version"],
        sport=pred["sport"],
        event=pred["event"],
        market=pred["market"],
        selection=pred["selection"],
        fair_prob=pred["fair_prob"],
        paper_price=pred["paper_price"],
        paper_book=pred["paper_book"],
        predicted_at=datetime.fromisoformat(pred["predicted_at"].replace("Z", "+00:00")),  # noqa: FURB162 (mirrors the brief)
        features_summary=pred["features_summary"],
    )


def _with(cases: dict, **changes) -> CanonicalPrediction:
    pred = dict(cases["canonical"]["basic"]["prediction"])
    pred.update(changes)
    return _build(pred)


def test_canonical_matches_fixture(cases):
    fx = cases["canonical"]["basic"]
    assert canonical_bytes(_build(fx["prediction"])).decode("utf-8") == fx["canonical"]


def test_canonical_millis_fixture(cases):
    fx = cases["canonical"]["millis"]
    assert canonical_bytes(_build(fx["prediction"])).decode("utf-8") == fx["canonical"]


def test_canonical_unicode_fixture(cases):
    fx = cases["canonical"]["unicode"]
    out = canonical_bytes(_build(fx["prediction"]))
    assert out.decode("utf-8") == fx["canonical"]
    # non-ASCII is emitted as raw UTF-8, never as \u escapes
    assert b"\\u" not in out
    assert "Åberg".encode() in out


def test_naive_or_non_utc_timestamp_rejected():
    with pytest.raises(ValueError):
        fmt_ts(datetime(2026, 10, 29, 13, 5, 0))
    with pytest.raises(ValueError):
        fmt_ts(datetime(2026, 10, 29, 15, 5, 0, tzinfo=timezone(timedelta(hours=2))))


def test_naive_timestamp_rejected_by_to_canonical_time():
    with pytest.raises(ValueError):
        to_canonical_time(datetime(2026, 10, 29, 13, 5, 0))


def test_sub_millisecond_rejected_and_truncation_helper():
    dt = datetime.fromisoformat("2026-10-29T13:05:07.123456+00:00")
    with pytest.raises(ValueError):
        fmt_ts(dt)
    assert fmt_ts(to_canonical_time(dt)) == "2026-10-29T13:05:07.123Z"


def test_to_canonical_time_converts_to_utc_and_truncates():
    dt = datetime(2026, 10, 29, 15, 5, 7, 999999, tzinfo=timezone(timedelta(hours=2)))
    out = to_canonical_time(dt)
    assert out.utcoffset() == timedelta(0)
    assert fmt_ts(out) == "2026-10-29T13:05:07.999Z"


def test_fmt_ts_whole_second_has_three_digits():
    assert fmt_ts(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2026-01-02T03:04:05.000Z"


def test_features_summary_values_must_be_strings(cases):
    with pytest.raises(ValueError):
        canonical_bytes(_with(cases, features_summary={"x": 1}))


def test_features_summary_keys_must_be_strings(cases):
    with pytest.raises(ValueError):
        canonical_bytes(_with(cases, features_summary={1: "x"}))


def test_non_nfc_text_rejected(cases):
    nfd = unicodedata.normalize("NFD", "Åberg")
    assert nfd != "Åberg"
    with pytest.raises(ValueError):
        canonical_bytes(_with(cases, features_summary={"note": nfd}))
    with pytest.raises(ValueError):
        canonical_bytes(_with(cases, features_summary={nfd: "x"}))
    with pytest.raises(ValueError):
        canonical_bytes(_with(cases, selection=nfd))


def test_non_string_field_rejected(cases):
    with pytest.raises(ValueError):
        canonical_bytes(_with(cases, sport=7))


def test_prob_and_price_formatting():
    assert fmt_prob(0.1834) == "0.183400"
    assert fmt_prob(0.1234565) == "0.123457"
    assert fmt_prob("0.5") == "0.500000"
    assert fmt_prob(Decimal("0.1234565")) == "0.123457"
    assert fmt_price("6.5") == "6.5000"
    assert fmt_price(2.00005) == "2.0001"
    assert fmt_price(Decimal("1.5")) == "1.5000"
    with pytest.raises(ValueError):
        fmt_prob(1.0)
    with pytest.raises(ValueError):
        fmt_prob(0.0000004)
    with pytest.raises(ValueError):
        fmt_price(1)


@pytest.mark.parametrize("bad", [0, 0.0, -0.1, 1.5, 0.9999999, float("nan"), float("inf"), True, None, "abc", ""])
def test_bad_probs_rejected(bad):
    with pytest.raises(ValueError):
        fmt_prob(bad)


@pytest.mark.parametrize("bad", [1, 1.0, 0.5, -3, 1.00004, float("nan"), float("inf"), True, None, "abc", ""])
def test_bad_prices_rejected(bad):
    with pytest.raises(ValueError):
        fmt_price(bad)


def test_rfc8785_agrees_with_sorted_compact_json(cases):
    for name in ("basic", "unicode", "millis"):
        fx = cases["canonical"][name]
        obj = json.loads(fx["canonical"])
        assert rfc8785.dumps(obj) == json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        assert rfc8785.dumps(obj) == canonical_bytes(_build(fx["prediction"]))


def test_canonical_millis_row_hash(cases):
    fx = cases["canonical"]["millis"]
    out = canonical_bytes(_build(fx["prediction"]))
    assert hashlib.sha256(bytes.fromhex(fx["salt_hex"]) + out).hexdigest() == fx["row_hash"]


def test_numpy_float64_accepted_like_float():
    np = pytest.importorskip("numpy")
    assert fmt_prob(np.float64(0.1834)) == "0.183400"
    assert fmt_prob(np.float64(0.1234565)) == "0.123457"
    assert fmt_price(np.float64(6.5)) == "6.5000"
    assert fmt_price(np.float64(2.00005)) == "2.0001"
    with pytest.raises(ValueError):
        fmt_prob(np.float64("nan"))
    with pytest.raises(ValueError):
        fmt_prob(np.float64(1.0))


class _NanosecondDatetime(datetime):
    """Stand-in for pandas.Timestamp, which keeps nanoseconds outside .microsecond."""

    nanosecond = 500


def _ns_dt(tz=UTC) -> datetime:
    return _NanosecondDatetime(2026, 10, 29, 13, 5, 7, 123000, tzinfo=tz)


def test_nanoseconds_rejected_not_dropped():
    with pytest.raises(ValueError):
        fmt_ts(_ns_dt())


def test_to_canonical_time_truncates_nanoseconds():
    for tz in (UTC, timezone(timedelta(hours=2))):
        out = to_canonical_time(_ns_dt(tz))
        assert getattr(out, "nanosecond", 0) == 0
        expected_hour = "13" if tz is UTC else "11"
        assert fmt_ts(out) == f"2026-10-29T{expected_hour}:05:07.123Z"


def test_pandas_timestamp_nanoseconds_rejected():
    pd = pytest.importorskip("pandas")
    ts = pd.Timestamp("2026-10-29T13:05:07.123000500Z")
    with pytest.raises(ValueError):
        fmt_ts(ts)
    assert fmt_ts(to_canonical_time(ts)) == "2026-10-29T13:05:07.123Z"
