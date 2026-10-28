"""v0.1.0 compatibility guard: records with a paper price hash exactly as they did in v0.1.0.

The expected hashes are literals, never read from cases.json, so a fixture edit cannot hide drift.
"""

from datetime import UTC, datetime

import pytest
from bundles import write_bundle

from cockpit_core.canonical import CanonicalPrediction, canonical_bytes
from cockpit_core.proof import row_hash
from cockpit_core.verify import verify_bundle

V010_SALT = bytes.fromhex("000102030405060708090a0b0c0d0e0f")

V010_ROW_HASHES = {
    "basic": "feb389ad6d89727d409ee325e6bcfa419a6e05297e5dc71b81ada43c668b0ed2",
    "unicode": "d176fa8fc345ecdbdb72a63d97e00d664a546f794c0bda484e6870404409fe72",
    "millis": "f5ab48cd357e6a6c049ebc97748c6e7af855c05ade898a5469a7d65150d17d2c",
}


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


@pytest.mark.parametrize("name", sorted(V010_ROW_HASHES))
def test_v010_vectors_byte_identical(cases, name):
    pred = cases["canonical"][name]["prediction"]
    assert "paper_price" in pred and "paper_book" in pred  # a v0.1.0 record always carries the pair
    assert row_hash(V010_SALT, canonical_bytes(_build(pred))).hex() == V010_ROW_HASHES[name]


# The v0.2.0 absent-pair vector: a record without a paper price (8 canonical fields). Built inline, never read
# from cases.json, and pinned like the v0.1.0 hashes above.
V020_ABSENT_PAIR_ROW_HASH = "0d4c4df74722297d0e8a95ad1bce1c12d2548bc81033e7ba38a299621943eb14"


def test_v020_absent_pair_vector_pinned():
    pred = CanonicalPrediction(
        model_version="golf-baseline@1",
        sport="golf",
        event="2026-mexico-open",
        market="2026-mexico-open:top_10",
        selection="2026-mexico-open:top_10:player-123",
        fair_prob=0.1834,
        paper_price=None,
        paper_book=None,
        predicted_at=datetime(2026, 10, 29, 13, 5, tzinfo=UTC),
        features_summary={"form_trend": "strong", "course_fit": "+"},
    )
    assert b"paper" not in canonical_bytes(pred)
    assert row_hash(V010_SALT, canonical_bytes(pred)).hex() == V020_ABSENT_PAIR_ROW_HASH


def test_v010_bundle_still_proven(tmp_path):
    path, anchors = write_bundle(tmp_path, [["a", "b"], ["c"]])
    assert anchors == {
        1: "a07726c5e42a7e4e6c1565d751d2ec6298ab1f11ef681b5d7cbb729d552e2c69",
        2: "a85f91393a3cf6f8e0e19df6ac63c80d5238d218e4210301731a07e2265bc001",
    }
    report = verify_bundle(path, anchors)
    assert report.ok, report.errors
    assert report.anchored
