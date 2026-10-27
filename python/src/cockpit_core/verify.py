# ruff: noqa: TRY004 (an unusable anchors file raises ValueError, caught by main)
"""Public verifier for a revealed track record: ``cockpit-verify <bundle> [--anchors anchors.json]``.

A bundle is a directory holding one model version's revealed predictions:

* ``manifest.json``: ``{"model_version": str, "n_batches": int}``
* ``rows.jsonl``: ``{"batch_seq": int, "index": int, "canonical": str, "salt": hex, "row_hash": hex}``
* ``batches.jsonl``: ``{"batch_seq": int, "n_rows": int, "merkle_root": hex, "chained_root": hex}``

The verifier recomputes every row hash, every batch Merkle root (from all of the batch's rows,
never from inclusion proofs), every row count and the whole chain from :data:`GENESIS`.

A bundle that only agrees with itself proves nothing: a forger can drop a row and recompute
every root. Proof comes from **anchors**, the chained roots recorded independently at the time
(in Rekor or OpenTimestamps). Here anchors are passed in as ``{batch_seq: chained_root_hex}``.
The chained root commits to each batch's row count, so an anchor pins both the rows and how
many there are. Only the final batch's anchor makes the report ``anchored``, because only it
covers every batch, and a report that is not ``ok`` is never ``anchored``.

Limit of caller-supplied anchors: if the anchors given stop at batch k, a bundle truncated to
batches 1..k (with batches k+1.. withheld) verifies as anchored. Anchors only prove what they
cover. The latest anchor must therefore come from independently fetched receipts (Phase 1C),
never from the bundle's owner.

Exit codes: 0 only when consistent and anchored; 2 when consistent but unanchored; 1 otherwise
(including usage errors, so a typo can never look like a verdict).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import rfc8785

from cockpit_core.canonical import fmt_price, fmt_prob, fmt_ts
from cockpit_core.proof import GENESIS, chain_root, merkle_root

__all__ = ["VerifyReport", "main", "verify_bundle"]

UNANCHORED_MESSAGE = "UNANCHORED: consistency only, not proof"

CANONICAL_KEYS = frozenset(
    {
        "model_version",
        "sport",
        "event",
        "market",
        "selection",
        "fair_prob",
        "paper_price",
        "paper_book",
        "predicted_at",
        "features_summary",
    }
)
_STRING_KEYS = ("model_version", "sport", "event", "market", "selection", "paper_book")
_ROW_KEYS = frozenset({"batch_seq", "index", "canonical", "salt", "row_hash"})
_BATCH_KEYS = frozenset({"batch_seq", "n_rows", "merkle_root", "chained_root"})
_MANIFEST_KEYS = frozenset({"model_version", "n_batches"})

_HASH_HEX = re.compile(r"[0-9a-f]{64}", re.ASCII)
_SALT_HEX = re.compile(r"[0-9a-f]{32}", re.ASCII)
_PROB = re.compile(r"0\.[0-9]{6}", re.ASCII)
_PRICE = re.compile(r"[0-9]+\.[0-9]{4}", re.ASCII)
_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", re.ASCII)
_SEQ_KEY = re.compile(r"[1-9][0-9]*", re.ASCII)
_U64_MAX = 2**64 - 1


@dataclass
class VerifyReport:
    """Outcome of :func:`verify_bundle`.

    ``ok``: the bundle is internally consistent and every given anchor matches.
    ``anchored``: anchors were given and the final batch's anchor matches the recomputed chain.
    Only ``ok and anchored`` is proof. ``errors`` names the batch (and row index) of each failure.
    """

    ok: bool
    anchored: bool
    n_batches: int
    n_rows: int
    final_chained_root: str | None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Row:
    line: int
    batch_seq: int
    index: int
    canonical: str
    salt: bytes
    row_hash: bytes

    @property
    def where(self) -> str:
        return f"batch {self.batch_seq} row {self.index}"


@dataclass(frozen=True)
class _Batch:
    line: int
    batch_seq: int
    n_rows: int
    merkle_root: bytes
    chained_root: bytes


# --- strict JSON ----------------------------------------------------------------------


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!a}")
        out[k] = v
    return out


def _reject_constant(name: str) -> object:
    raise ValueError(f"non-standard JSON constant {name}")


def _loads(text: str) -> object:
    """``json.loads`` that rejects duplicate keys and NaN/Infinity (other parsers would disagree on them)."""
    return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)


def _read_text(path: Path, name: str, errors: list[str]) -> str | None:
    """Read a bundle file as UTF-8 whatever the OS locale; record an error and return None if impossible."""
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        errors.append(f"{name}: missing")
    except OSError as exc:
        errors.append(f"{name}: cannot be read ({type(exc).__name__})")
    except UnicodeDecodeError:
        errors.append(f"{name}: not valid UTF-8")
    return None


def _jsonl(text: str, name: str, errors: list[str]) -> list[tuple[int, object]]:
    """Parse JSON Lines. Splits on ``\\n`` only: U+2028 and friends may appear raw inside JSON strings."""
    records = []
    for n, raw in enumerate(text.split("\n"), start=1):
        line = raw.removesuffix("\r")
        if not line.strip():
            continue
        try:
            records.append((n, _loads(line)))
        except (ValueError, RecursionError) as exc:
            errors.append(f"{name} line {n}: not valid JSON ({exc})")
    return records


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _keys_problem(record: object, expected: frozenset[str]) -> str | None:
    if not isinstance(record, dict):
        return "must be a JSON object"
    keys = set(record)
    if keys == expected:
        return None
    missing, extra = sorted(expected - keys), sorted(keys - expected)
    return f"wrong keys (missing {missing}, unexpected {[ascii(k) for k in extra]})"


# --- parsing records ------------------------------------------------------------------


def _parse_manifest(text: str, errors: list[str]) -> tuple[str | None, int | None]:
    try:
        record = _loads(text)
    except (ValueError, RecursionError) as exc:
        errors.append(f"manifest.json: not valid JSON ({exc})")
        return None, None
    problem = _keys_problem(record, _MANIFEST_KEYS)
    if problem:
        errors.append(f"manifest.json: {problem}")
        return None, None
    model_version, n_batches = record["model_version"], record["n_batches"]  # type: ignore[index]
    if not isinstance(model_version, str):
        errors.append("manifest.json: model_version must be a string")
        model_version = None
    if not _is_int(n_batches) or n_batches < 0:
        errors.append(f"manifest.json: n_batches must be a non-negative integer, got {n_batches!a}")
        n_batches = None
    return model_version, n_batches


def _parse_row(n: int, record: object, errors: list[str]) -> _Row | None:
    problem = _keys_problem(record, _ROW_KEYS)
    if problem:
        errors.append(f"rows.jsonl line {n}: {problem}")
        return None
    assert isinstance(record, dict)
    seq, index = record["batch_seq"], record["index"]
    if not (_is_int(seq) and _is_int(index) and 0 <= seq <= _U64_MAX and 0 <= index <= _U64_MAX):
        errors.append(f"rows.jsonl line {n}: batch_seq and index must be integers in [0, 2**64)")
        return None
    where = f"batch {seq} row {index}"
    bad = []
    if not isinstance(record["canonical"], str):
        bad.append("canonical must be a string")
    if not isinstance(record["salt"], str) or not _SALT_HEX.fullmatch(record["salt"]):
        bad.append("salt must be 32 lowercase hex digits")
    if not isinstance(record["row_hash"], str) or not _HASH_HEX.fullmatch(record["row_hash"]):
        bad.append("row_hash must be 64 lowercase hex digits")
    if bad:
        errors.extend(f"{where}: {b} (rows.jsonl line {n})" for b in bad)
        return None
    return _Row(n, seq, index, record["canonical"], bytes.fromhex(record["salt"]), bytes.fromhex(record["row_hash"]))


def _parse_batch(n: int, record: object, errors: list[str]) -> _Batch | None:
    problem = _keys_problem(record, _BATCH_KEYS)
    if problem:
        errors.append(f"batches.jsonl line {n}: {problem}")
        return None
    assert isinstance(record, dict)
    seq = record["batch_seq"]
    if not _is_int(seq) or not 0 <= seq <= _U64_MAX:
        errors.append(f"batches.jsonl line {n}: batch_seq must be an integer in [0, 2**64)")
        return None
    where = f"batch {seq}"
    bad = []
    if not _is_int(record["n_rows"]) or not 0 <= record["n_rows"] <= _U64_MAX:
        bad.append("n_rows must be an integer in [0, 2**64)")
    for key in ("merkle_root", "chained_root"):
        if not isinstance(record[key], str) or not _HASH_HEX.fullmatch(record[key]):
            bad.append(f"{key} must be 64 lowercase hex digits")
    if bad:
        errors.extend(f"{where}: {b} (batches.jsonl line {n})" for b in bad)
        return None
    return _Batch(n, seq, record["n_rows"], bytes.fromhex(record["merkle_root"]), bytes.fromhex(record["chained_root"]))


def _parse_anchors(anchors: Mapping[int, str] | None, errors: list[str]) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    for seq, value in (anchors or {}).items():
        if not _is_int(seq):
            errors.append(f"anchors: batch key must be an integer, got {seq!a}")
            continue
        if not isinstance(value, str) or not _HASH_HEX.fullmatch(value.lower()):
            errors.append(f"batch {seq}: anchor must be 64 hex digits, got {value!a}")
            continue
        out[seq] = bytes.fromhex(value)
    return out


# --- check 5: canonical bytes ----------------------------------------------------------


def _nfc_problem(value: object) -> str | None:
    if not isinstance(value, str):
        return "must be a string"
    if not unicodedata.is_normalized("NFC", value):
        return "is not Unicode NFC"
    return None


def _formatted(fmt: object, value: str) -> bool:
    """True if the publisher's formatter maps ``value`` to itself (no leading zeros, in range)."""
    try:
        return fmt(value) == value  # type: ignore[operator]
    except ValueError:
        return False


def _check_shape(obj: object, model_version: str | None) -> list[str]:
    """Cheap shape check: exactly the 10 canonical keys, canonical number and time strings, NFC text."""
    if not isinstance(obj, dict):
        return ["canonical must be a JSON object"]
    problems = []
    keys = set(obj)
    if keys != CANONICAL_KEYS:
        missing, extra = sorted(CANONICAL_KEYS - keys), sorted(keys - CANONICAL_KEYS)
        problems.append(f"canonical has wrong keys (missing {missing}, unexpected {[ascii(k) for k in extra]})")
    for key in _STRING_KEYS:
        if key in obj and (p := _nfc_problem(obj[key])):
            problems.append(f"{key} {p}")

    prob = obj.get("fair_prob")
    if "fair_prob" in obj and not (isinstance(prob, str) and _PROB.fullmatch(prob) and _formatted(fmt_prob, prob)):
        problems.append(f"fair_prob must be a 6 dp string strictly between 0 and 1, got {prob!a}")
    price = obj.get("paper_price")
    if "paper_price" in obj and not (
        isinstance(price, str) and _PRICE.fullmatch(price) and _formatted(fmt_price, price)
    ):
        problems.append(f"paper_price must be a 4 dp string greater than 1, got {price!a}")
    ts = obj.get("predicted_at")
    if "predicted_at" in obj and not (isinstance(ts, str) and _TS.fullmatch(ts) and _canonical_time(ts)):
        problems.append(f"predicted_at must be a real UTC time as YYYY-MM-DDTHH:MM:SS.mmmZ, got {ts!a}")

    features = obj.get("features_summary")
    if "features_summary" in obj:
        if not isinstance(features, dict):
            problems.append("features_summary must be an object of string to string")
        else:
            for k, v in features.items():
                if (p := _nfc_problem(k)) or (p := _nfc_problem(v)):
                    problems.append(f"features_summary[{k!a}] {p}")

    mv = obj.get("model_version")
    if model_version is not None and isinstance(mv, str) and mv != model_version:
        problems.append(f"model_version {mv!a} differs from the manifest's {model_version!a}")
    return problems


def _canonical_time(ts: str) -> bool:
    try:
        return fmt_ts(datetime.fromisoformat(ts.replace("Z", "+00:00"))) == ts  # noqa: FURB162
    except ValueError:
        return False


def _check_canonical(text: str, model_version: str | None) -> tuple[list[str], bytes | None]:
    """Check 5. Returns the problems found and the canonical's UTF-8 bytes (None if it has none)."""
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        return ["canonical is not encodable as UTF-8 (lone surrogate)"], None
    try:
        obj = _loads(text)
    except (ValueError, RecursionError) as exc:
        return [f"canonical is not valid JSON ({exc})"], data
    problems = []
    try:
        if rfc8785.dumps(obj) != data:
            problems.append("canonical does not re-canonicalise (RFC 8785) to identical bytes")
    except (ValueError, TypeError, RecursionError) as exc:
        problems.append(f"canonical cannot be re-canonicalised ({type(exc).__name__})")
    problems.extend(_check_shape(obj, model_version))
    return problems, data


# --- the verifier ---------------------------------------------------------------------


_MAX_LISTED = 20


def _listed(items: list[int]) -> str:
    """At most ``_MAX_LISTED`` items, so a hostile bundle cannot blow up the error text."""
    shown = ", ".join(str(i) for i in items[:_MAX_LISTED])
    return f"[{shown}, ... {len(items)} in all]" if len(items) > _MAX_LISTED else f"[{shown}]"


def _index_problem(indexes: list[int]) -> str | None:
    """Check 4: the indexes (sorted) must be exactly 0..n-1.

    Work and message size depend only on the number of rows, never on the index values:
    an index of 10**18 is reported as out of range, not expanded into a range.
    """
    n = len(indexes)
    if indexes == list(range(n)):
        return None
    in_range = [i for i in indexes if i < n]
    out_of_range = sorted(i for i in indexes if i >= n)
    counts = Counter(in_range)
    dups = sorted(i for i, c in counts.items() if c > 1)
    missing = sorted(set(range(n)) - set(in_range))
    return (
        f"row indexes are not exactly 0..{n - 1} (duplicated {_listed(dups)}, missing {_listed(missing)}, "
        f"out of range {_listed(out_of_range)})"
    )


def verify_bundle(path: Path, anchors: Mapping[int, str] | None = None) -> VerifyReport:
    """Recompute everything in the bundle at ``path`` and compare it with ``anchors``.

    Every check runs and every failure is collected; nothing stops at the first error.
    """
    path = Path(path)
    errors: list[str] = []
    anchor_roots = _parse_anchors(anchors, errors)

    # 1. manifest, and its batch count
    model_version: str | None = None
    n_batches_claimed: int | None = None
    if (text := _read_text(path / "manifest.json", "manifest.json", errors)) is not None:
        model_version, n_batches_claimed = _parse_manifest(text, errors)
    batch_records = []
    if (text := _read_text(path / "batches.jsonl", "batches.jsonl", errors)) is not None:
        batch_records = _jsonl(text, "batches.jsonl", errors)
    row_records = []
    if (text := _read_text(path / "rows.jsonl", "rows.jsonl", errors)) is not None:
        row_records = _jsonl(text, "rows.jsonl", errors)
    if n_batches_claimed is not None and n_batches_claimed != len(batch_records):
        errors.append(f"manifest.json: n_batches is {n_batches_claimed} but batches.jsonl has {len(batch_records)}")

    # 2. batch_seq is exactly 1..N
    batches: dict[int, _Batch] = {}
    for n, record in batch_records:
        if (b := _parse_batch(n, record, errors)) is None:
            continue
        if b.batch_seq in batches:
            errors.append(f"batch {b.batch_seq}: duplicate batch line (batches.jsonl line {n})")
            continue
        batches[b.batch_seq] = b
    seqs = sorted(batches)
    if seqs != list(range(1, len(batch_records) + 1)):
        shown = seqs if len(seqs) <= 20 else [*seqs[:20], "..."]
        errors.append(f"batches.jsonl: batch_seq must be exactly 1..{len(batch_records)}, got {shown}")

    # 3. every row belongs to a batch
    rows_by_batch: dict[int, list[_Row]] = {seq: [] for seq in seqs}
    for n, record in row_records:
        if (r := _parse_row(n, record, errors)) is None:
            continue
        if r.batch_seq not in rows_by_batch:
            errors.append(f"{r.where}: batch_seq {r.batch_seq} has no batch line (rows.jsonl line {r.line})")
            continue
        rows_by_batch[r.batch_seq].append(r)

    prev = GENESIS
    chain: dict[int, bytes] = {}
    n_rows_total = 0
    for seq in seqs:
        batch = batches[seq]
        rows = sorted(rows_by_batch[seq], key=lambda r: (r.index, r.line))  # (batch_seq, index), not file order
        n_rows_total += len(rows)

        # 4. indexes are exactly 0..n-1
        if (p := _index_problem([r.index for r in rows])) is not None:
            errors.append(f"batch {seq}: {p}")

        leaves = []
        for r in rows:
            # 5. canonical bytes re-canonicalise, have the canonical shape and the manifest's model_version
            problems, data = _check_canonical(r.canonical, model_version)
            errors.extend(f"{r.where}: {p}" for p in problems)
            # 6. row_hash == sha256(salt || canonical)
            if data is None:
                leaves.append(r.row_hash)
                continue
            actual = hashlib.sha256(r.salt + data).digest()
            if actual != r.row_hash:
                errors.append(f"{r.where}: row_hash does not match sha256(salt || canonical)")
            leaves.append(actual)

        # 7. merkle_root over the recomputed row hashes, in index order
        root = merkle_root(leaves)
        if root != batch.merkle_root:
            errors.append(
                f"batch {seq}: merkle_root mismatch (bundle {batch.merkle_root.hex()}, recomputed {root.hex()})"
            )
        # 8. n_rows matches the rows actually present
        if batch.n_rows != len(rows):
            errors.append(f"batch {seq}: n_rows is {batch.n_rows} but the bundle has {len(rows)} rows")
        # 9. chained_root, recomputed from GENESIS with the real root and the real row count
        prev = chain_root(prev, root, len(rows))
        chain[seq] = prev
        if prev != batch.chained_root:
            errors.append(
                f"batch {seq}: chained_root mismatch (bundle {batch.chained_root.hex()}, recomputed {prev.hex()})"
            )

    # 10. every anchor given equals the recomputed chained root of its batch
    for seq in sorted(anchor_roots):
        if seq not in chain:
            errors.append(f"batch {seq}: anchor given but the bundle has no such batch")
        elif chain[seq] != anchor_roots[seq]:
            errors.append(
                f"batch {seq}: chained_root does not match the anchor "
                f"(anchor {anchor_roots[seq].hex()}, recomputed {chain[seq].hex()})"
            )

    final_seq = seqs[-1] if seqs else None
    final_root = chain[final_seq] if final_seq is not None else None
    # never anchored when anything failed: that includes an anchor for a batch beyond the bundle's final one
    anchored = not errors and final_root is not None and anchor_roots.get(final_seq) == final_root  # type: ignore[arg-type]
    return VerifyReport(
        ok=not errors,
        anchored=anchored,
        n_batches=len(seqs),
        n_rows=n_rows_total,
        final_chained_root=final_root.hex() if final_root is not None else None,
        errors=errors,
    )


# --- command line ---------------------------------------------------------------------


class _ArgumentParser(argparse.ArgumentParser):
    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        # usage errors (argparse uses 2) and --help must never look like a verdict: always exit 1
        if message:
            self._print_message(message)
        raise _UsageExit


class _UsageExit(Exception):
    pass


def _load_anchors_file(path: Path) -> dict[int, str]:
    record = _loads(path.read_bytes().decode("utf-8"))
    if not isinstance(record, dict):
        raise ValueError("must be a JSON object of batch_seq to chained root hex")
    out: dict[int, str] = {}
    for key, value in record.items():
        if not _SEQ_KEY.fullmatch(key):
            raise ValueError(f"key {key!a} is not a positive batch_seq")
        if not isinstance(value, str):
            raise ValueError(f"anchor for batch {key} must be a string")
        out[int(key)] = value
    return out


def _shown(path: Path) -> str:
    """A path for printing on any console encoding (non-ASCII becomes backslash escapes)."""
    return str(path).encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    """Verify a bundle and print the report. Returns 0 (proven), 2 (consistent, unanchored) or 1 (failed)."""
    parser = _ArgumentParser(
        prog="cockpit-verify",
        description="Recompute a Cockpit reveal bundle and compare it with independently recorded anchors.",
        epilog="Exit codes: 0 consistent and anchored; 2 consistent but unanchored; 1 anything else.",
    )
    parser.add_argument("bundle", type=Path, help="bundle directory (manifest.json, rows.jsonl, batches.jsonl)")
    parser.add_argument("--anchors", type=Path, help='anchors.json: {"<batch_seq>": "<chained_root hex>"}')
    try:
        args = parser.parse_args(argv)
    except _UsageExit:
        return 1

    anchors = None
    if args.anchors is not None:
        try:
            anchors = _load_anchors_file(args.anchors)
        except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
            print(f"FAILED: anchors file {_shown(args.anchors)} unusable: {type(exc).__name__}: {exc}")
            return 1

    report = verify_bundle(args.bundle, anchors)
    print(f"bundle: {_shown(args.bundle)}")
    print(f"batches: {report.n_batches}  rows: {report.n_rows}")
    print(f"final chained root: {report.final_chained_root}")
    print(f"anchors given: {len(anchors) if anchors else 0}  anchored: {'yes' if report.anchored else 'no'}")
    for e in report.errors:
        print(f"ERROR {e}")
    if not report.ok:
        print(f"FAILED: {len(report.errors)} error(s)")
        return 1
    if not report.anchored:
        print(UNANCHORED_MESSAGE)
        return 2
    print(f"VERIFIED: consistent, and batch {report.n_batches}'s chained root matches its anchor")
    return 0
