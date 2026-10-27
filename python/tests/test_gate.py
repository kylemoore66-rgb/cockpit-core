import copy

import pytest
from jsonschema import ValidationError

from cockpit_core.gate import criteria_hash, validate_criteria

VALID = {
    "counted_prediction": "last_committed_before_close",
    "paper_price_rule": "best price across tracked books at commit time",
    "clv_reference": {"books": ["pinnacle", "circa"], "method": "shin"},
    "close_age_limit_seconds": 600,
    "min_picks": 200,
    "min_events": 20,
    "test": {"name": "cluster_bootstrap_mean_clv", "alpha": 0.05, "ci_level": 0.95},
}


def _valid() -> dict:
    return copy.deepcopy(VALID)


def test_valid_criteria_pass_and_hash_is_stable_across_key_order():
    validate_criteria(_valid())
    reordered = {
        "test": {"ci_level": 0.95, "alpha": 0.05, "name": "cluster_bootstrap_mean_clv"},
        "min_events": 20,
        "min_picks": 200,
        "close_age_limit_seconds": 600,
        "clv_reference": {"method": "shin", "books": ["pinnacle", "circa"]},
        "paper_price_rule": "best price across tracked books at commit time",
        "counted_prediction": "last_committed_before_close",
    }
    h = criteria_hash(_valid())
    assert h == criteria_hash(reordered)
    assert len(h) == 64
    assert h == h.lower()
    # the hash commits to content: one changed value changes it
    other = _valid()
    other["min_picks"] = 201
    assert criteria_hash(other) != h


def test_optional_notes_allowed():
    c = _valid()
    c["notes"] = "pre-registered 2026-10-27"
    validate_criteria(c)


@pytest.mark.parametrize(
    "field",
    [
        "counted_prediction",
        "paper_price_rule",
        "clv_reference",
        "close_age_limit_seconds",
        "min_picks",
        "min_events",
        "test",
    ],
)
def test_missing_required_field_raises(field):
    c = _valid()
    del c[field]
    with pytest.raises(ValidationError):
        validate_criteria(c)
    with pytest.raises(ValidationError):
        criteria_hash(c)


@pytest.mark.parametrize(
    ("parent", "key"),
    [
        ("clv_reference", "books"),
        ("clv_reference", "method"),
        ("test", "name"),
        ("test", "alpha"),
        ("test", "ci_level"),
    ],
)
def test_missing_nested_field_raises(parent, key):
    c = _valid()
    del c[parent][key]
    with pytest.raises(ValidationError):
        validate_criteria(c)


def test_clv_reference_needs_two_books():
    c = _valid()
    c["clv_reference"]["books"] = ["pinnacle"]
    with pytest.raises(ValidationError):
        validate_criteria(c)
    c["clv_reference"]["books"] = []
    with pytest.raises(ValidationError):
        validate_criteria(c)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(counted_prediction="first_committed"),
        lambda c: c.update(paper_price_rule=""),
        lambda c: c.update(close_age_limit_seconds=0),
        lambda c: c.update(min_picks=0),
        lambda c: c.update(min_events=1.5),
        lambda c: c.update(min_picks=True),
        lambda c: c["clv_reference"].update(method="average"),
        lambda c: c["test"].update(name="t_test"),
        lambda c: c["test"].update(alpha=0),
        lambda c: c["test"].update(alpha=0.6),
        lambda c: c["test"].update(ci_level=0.5),
        lambda c: c["test"].update(ci_level=1),
        lambda c: c.update(extra_field=1),
        lambda c: c["test"].update(extra_field=1),
        lambda c: c.update(notes=3),
    ],
)
def test_invalid_values_raise(mutate):
    c = _valid()
    mutate(c)
    with pytest.raises(ValidationError):
        validate_criteria(c)


def test_boundary_values_accepted():
    c = _valid()
    c["test"]["alpha"] = 0.5
    c["test"]["ci_level"] = 0.999
    c["close_age_limit_seconds"] = 1
    validate_criteria(c)
