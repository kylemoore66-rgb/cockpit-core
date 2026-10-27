"""Gate criteria: the pre-registered success criteria for a model's shadow period.

``criteria_hash`` is the value committed publicly before the shadow period starts, so it
must not depend on key order or whitespace: it is the SHA-256 of the RFC 8785 bytes.

The schema lives once, at ``schemas/gate-criteria.schema.json`` in the repo root (the TypeScript
package and the website read the same file). Wheels carry a copy at
``cockpit_core/gate-criteria.schema.json`` (hatch ``force-include``); a source checkout or editable
install reads the repo-root file directly.
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator

_SCHEMA_NAME = "gate-criteria.schema.json"
_CANDIDATES = (
    Path(__file__).with_name(_SCHEMA_NAME),  # installed wheel
    Path(__file__).parents[3] / "schemas" / _SCHEMA_NAME,  # source checkout / editable install
)


@cache
def _validator() -> Draft202012Validator:
    for path in _CANDIDATES:
        if path.is_file():
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            return Draft202012Validator(schema)
    raise FileNotFoundError(f"{_SCHEMA_NAME} not found; looked in: " + ", ".join(str(p) for p in _CANDIDATES))


def validate_criteria(c: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``c`` is not a valid gate-criteria document."""
    _validator().validate(c)


def criteria_hash(c: dict) -> str:
    """Hex SHA-256 of the RFC 8785 bytes of ``c``, after validation."""
    validate_criteria(c)
    return hashlib.sha256(rfc8785.dumps(c)).hexdigest()
