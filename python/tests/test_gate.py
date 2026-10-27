import copy
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import ValidationError

from cockpit_core import gate
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


def test_packaged_schema_is_byte_equal_to_repo_schema():
    """The package ships its own copy of the schema; it must never drift from the repo-root file."""
    repo_schema = Path(__file__).parents[2] / "schemas" / "gate-criteria.schema.json"
    packaged = files("cockpit_core").joinpath("gate-criteria.schema.json")
    assert packaged.is_file(), "cockpit_core/gate-criteria.schema.json is missing from the package"
    assert packaged.read_bytes() == repo_schema.read_bytes()


def test_gate_reads_only_the_packaged_schema():
    assert not hasattr(gate, "_CANDIDATES"), "no repo-root fallback: the package copy is the only source"


@pytest.mark.parametrize(
    "books",
    [
        ["pinnacle", ""],  # an empty book name
        ["pinnacle", "pinnacle"],  # the same book twice is not two books
        ["pinnacle", "circa", "pinnacle"],
    ],
)
def test_clv_reference_books_must_be_distinct_non_empty_names(books):
    c = _valid()
    c["clv_reference"]["books"] = books
    with pytest.raises(ValidationError):
        validate_criteria(c)
    with pytest.raises(ValidationError):
        criteria_hash(c)


NFD_ABERG = "Åberg"  # "Åberg" decomposed: same text to a reader, different bytes and hash


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(paper_price_rule=f"best price, {NFD_ABERG} rule"),
        lambda c: c.update(notes=NFD_ABERG),
        lambda c: c["clv_reference"].update(books=["pinnacle", NFD_ABERG]),
        lambda c: c.update({NFD_ABERG: "x"}),  # a key: rejected as non-NFC before the schema sees it
    ],
)
def test_non_nfc_string_anywhere_is_a_value_error(mutate):
    c = _valid()
    mutate(c)
    with pytest.raises(ValueError, match="NFC"):
        validate_criteria(c)
    with pytest.raises(ValueError, match="NFC"):
        criteria_hash(c)


def test_nfc_non_ascii_text_is_accepted():
    c = _valid()
    c["notes"] = "Åberg"  # precomposed: NFC
    validate_criteria(c)
    assert len(criteria_hash(c)) == 64
