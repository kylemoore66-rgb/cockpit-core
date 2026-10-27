"""Gate criteria: the pre-registered success criteria for a model's shadow period.

``criteria_hash`` is the value committed publicly before the shadow period starts, so it
must not depend on key order or whitespace: it is the SHA-256 of the RFC 8785 bytes.

The schema is published at ``schemas/gate-criteria.schema.json`` in the repo root. The package
carries a byte-identical copy at ``cockpit_core/gate-criteria.schema.json`` (a test keeps the two
equal) and reads only that copy, so a wheel, an sdist build and a source checkout all behave the
same. The TypeScript package does not read the schema; gate criteria are Python-only.
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from importlib.resources import files

import rfc8785
from jsonschema import Draft202012Validator

_SCHEMA_NAME = "gate-criteria.schema.json"


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(files("cockpit_core").joinpath(_SCHEMA_NAME).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_criteria(c: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``c`` is not a valid gate-criteria document."""
    _validator().validate(c)


def criteria_hash(c: dict) -> str:
    """Hex SHA-256 of the RFC 8785 bytes of ``c``, after validation."""
    validate_criteria(c)
    return hashlib.sha256(rfc8785.dumps(c)).hexdigest()
