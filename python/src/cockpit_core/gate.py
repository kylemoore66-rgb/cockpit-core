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
import unicodedata
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


def _require_nfc(value: object, where: str) -> None:
    """Raise ValueError on any string (key or value, at any depth) that is not Unicode NFC.

    Two documents that read the same but differ in normalisation would hash differently, so a
    pre-registered criterion could be "re-committed" under a different hash. Only NFC is accepted.
    """
    if isinstance(value, str):
        if not unicodedata.is_normalized("NFC", value):
            raise ValueError(f"{where} is not Unicode NFC: {value[:40]!r}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _require_nfc(key, f"key in {where}")
            _require_nfc(item, f"{where}.{key}" if isinstance(key, str) else where)
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _require_nfc(item, f"{where}[{i}]")


def validate_criteria(c: dict) -> None:
    """Check ``c`` is a valid gate-criteria document.

    Raises ValueError if any string in it (key or value) is not Unicode NFC, then
    ``jsonschema.ValidationError`` if it does not match the schema.
    """
    _require_nfc(c, "criteria")
    _validator().validate(c)


def criteria_hash(c: dict) -> str:
    """Hex SHA-256 of the RFC 8785 bytes of ``c``, after validation (see :func:`validate_criteria`)."""
    validate_criteria(c)
    return hashlib.sha256(rfc8785.dumps(c)).hexdigest()
