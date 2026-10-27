# ruff: noqa: TRY004 (contract: every invalid argument raises ValueError, never TypeError)
"""Proof primitives: salted row hashes, RFC 6962 Merkle trees, chained batch roots and day roots.

These values are published in transparency logs, so anyone must be able to recompute
them in any language from this description alone:

* Hash: SHA-256 everywhere.
* Row hash: ``sha256(salt || canonical)``, where ``salt`` is 16 random bytes and
  ``canonical`` is the RFC 8785 bytes from :func:`cockpit_core.canonical.canonical_bytes`.
* Merkle tree: RFC 6962 section 2.1. Leaf hash ``sha256(0x00 || d)``, interior node
  ``sha256(0x01 || left || right)``, split at the largest power of two strictly below
  ``n``. The empty tree's root is ``sha256(b"")``. Leaves are raw bytes (the function
  applies the leaf prefix itself).
* Inclusion proof: RFC 6962 section 2.1.1 ``PATH``; verification follows RFC 9162
  section 2.1.3.2.
* Batch chain: ``sha256(b"cockpit-chain-v1" || prev || batch_root || n_rows_be64)``.
* Day root: ``sha256(b"cockpit-day-v1" || prev_day || merkle_root(chained_roots) ||
  len(chained_roots)_be64)``.
* Genesis: 32 zero bytes, the ``prev`` of the first batch and of the first day.

Only the standard library is used.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence

__all__ = [
    "GENESIS",
    "HASH_SIZE",
    "SALT_SIZE",
    "chain_root",
    "day_root",
    "inclusion_proof",
    "merkle_root",
    "new_salt",
    "row_hash",
    "verify_inclusion",
]

HASH_SIZE = 32
SALT_SIZE = 16
GENESIS: bytes = bytes(HASH_SIZE)

_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"
_CHAIN_TAG = b"cockpit-chain-v1"
_DAY_TAG = b"cockpit-day-v1"
_U64_MAX = 2**64 - 1


# --- argument checks ------------------------------------------------------------------


def _require_bytes(value: object, what: str) -> bytes:
    if not isinstance(value, bytes):
        raise ValueError(f"{what} must be bytes, got {type(value).__name__}")
    return value


def _require_hash(value: object, what: str) -> bytes:
    _require_bytes(value, what)
    if len(value) != HASH_SIZE:  # type: ignore[arg-type]
        raise ValueError(f"{what} must be {HASH_SIZE} bytes, got {len(value)}")  # type: ignore[arg-type]
    return value  # type: ignore[return-value]


def _require_int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what} must be an int, got {type(value).__name__}")
    return value


def _require_sequence(value: object, what: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray, memoryview)) or not isinstance(value, Sequence):
        raise ValueError(f"{what} must be a sequence (list or tuple), got {type(value).__name__}")
    return value


def _require_byte_items(value: object, what: str) -> list[bytes]:
    items = _require_sequence(value, what)
    return [_require_bytes(item, f"{what}[{i}]") for i, item in enumerate(items)]


# --- salts and row hashes -------------------------------------------------------------


def new_salt() -> bytes:
    """Return a fresh 16-byte salt from the OS CSPRNG."""
    return secrets.token_bytes(SALT_SIZE)


def row_hash(salt: bytes, canonical: bytes) -> bytes:
    """Return ``sha256(salt || canonical)``.

    Raises ValueError if either argument is not ``bytes`` or ``salt`` is not exactly 16 bytes.
    """
    _require_bytes(salt, "salt")
    _require_bytes(canonical, "canonical")
    if len(salt) != SALT_SIZE:
        raise ValueError(f"salt must be {SALT_SIZE} bytes, got {len(salt)}")
    return hashlib.sha256(salt + canonical).digest()


# --- RFC 6962 Merkle tree -------------------------------------------------------------


def _leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(_LEAF_PREFIX + data).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(_NODE_PREFIX + left + right).digest()


def _split(n: int) -> int:
    """Largest power of two strictly less than ``n`` (``n >= 2``)."""
    return 1 << ((n - 1).bit_length() - 1)


def _mth(hashes: list[bytes], lo: int, hi: int) -> bytes:
    """RFC 6962 MTH over the leaf hashes ``hashes[lo:hi]`` (non-empty)."""
    n = hi - lo
    if n == 1:
        return hashes[lo]
    k = _split(n)
    return _node_hash(_mth(hashes, lo, lo + k), _mth(hashes, lo + k, hi))


def _path(m: int, hashes: list[bytes], lo: int, hi: int) -> list[bytes]:
    """RFC 6962 PATH(m, D[lo:hi]) over leaf hashes, ordered leaf-to-root."""
    n = hi - lo
    if n == 1:
        return []
    k = _split(n)
    if m < k:
        return [*_path(m, hashes, lo, lo + k), _mth(hashes, lo + k, hi)]
    return [*_path(m - k, hashes, lo + k, hi), _mth(hashes, lo, lo + k)]


def merkle_root(leaves: Sequence[bytes]) -> bytes:
    """Return the RFC 6962 Merkle Tree Hash of ``leaves`` (raw leaf data, in order).

    The empty tree's root is ``sha256(b"")``. Raises ValueError if ``leaves`` is not a
    list/tuple of ``bytes`` (a ``str`` or ``bytes`` object itself is rejected).
    """
    items = _require_byte_items(leaves, "leaves")
    if not items:
        return hashlib.sha256(b"").digest()
    hashes = [_leaf_hash(d) for d in items]
    return _mth(hashes, 0, len(hashes))


def inclusion_proof(leaves: Sequence[bytes], index: int) -> list[bytes]:
    """Return the RFC 6962 audit path for ``leaves[index]``, ordered from leaf to root.

    A single-leaf tree has an empty proof. Raises ValueError if ``leaves`` is not a
    non-empty list/tuple of ``bytes``, or ``index`` is not an int in ``[0, len(leaves))``.
    """
    items = _require_byte_items(leaves, "leaves")
    _require_int(index, "index")
    if not items:
        raise ValueError("cannot prove inclusion in an empty tree")
    if not 0 <= index < len(items):
        raise ValueError(f"index {index} out of range for {len(items)} leaves")
    hashes = [_leaf_hash(d) for d in items]
    return _path(index, hashes, 0, len(hashes))


def verify_inclusion(leaf: bytes, index: int, tree_size: int, proof: Sequence[bytes], root: bytes) -> bool:
    """Check that raw leaf data ``leaf`` sits at ``index`` in a tree of ``tree_size`` with ``root``.

    Implements RFC 9162 section 2.1.3.2. Returns False (never raises) for any proof
    that does not verify, including: a tampered or reordered proof element, a proof
    element that is not 32 bytes, a proof with too few or too many elements, the wrong
    leaf, the wrong root, a wrong or negative ``index``, ``index >= tree_size``, and a
    zero or negative ``tree_size``, and a ``tree_size`` the proof's shape cannot fit.

    The root alone does not commit to ``tree_size``: when two sizes give the same path
    shape for ``index`` (for example index 2 in trees of 5 and 6 leaves), both verify.
    Bind the size separately, as :func:`chain_root` does with ``n_rows``.

    Raises ValueError only for arguments of the wrong type or size: ``leaf`` not
    ``bytes``; ``index`` or ``tree_size`` not an int (bools rejected); ``proof`` not a
    list/tuple, or any element not ``bytes``; ``root`` not 32 ``bytes``.
    """
    _require_bytes(leaf, "leaf")
    _require_int(index, "index")
    _require_int(tree_size, "tree_size")
    path = _require_byte_items(proof, "proof")
    _require_hash(root, "root")

    if index < 0 or index >= tree_size:
        return False
    fn, sn = index, tree_size - 1
    r = _leaf_hash(leaf)
    for p in path:
        if len(p) != HASH_SIZE or sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = _node_hash(p, r)
            while fn != 0 and not fn & 1:
                fn >>= 1
                sn >>= 1
        else:
            r = _node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root


# --- chained batch roots and day roots ------------------------------------------------


def chain_root(prev: bytes, batch_root: bytes, n_rows: int) -> bytes:
    """Return ``sha256(b"cockpit-chain-v1" || prev || batch_root || n_rows as 8-byte big-endian)``.

    ``prev`` is :data:`GENESIS` for the first batch of a model version, otherwise the
    previous batch's chained root. Raises ValueError if ``prev`` or ``batch_root`` is not
    32 bytes, or ``n_rows`` is not an int in ``[0, 2**64)``.
    """
    _require_hash(prev, "prev")
    _require_hash(batch_root, "batch_root")
    _require_int(n_rows, "n_rows")
    if not 0 <= n_rows <= _U64_MAX:
        raise ValueError(f"n_rows must be in [0, 2**64), got {n_rows}")
    return hashlib.sha256(_CHAIN_TAG + prev + batch_root + n_rows.to_bytes(8, "big")).digest()


def day_root(prev_day: bytes, chained_roots: Sequence[bytes]) -> bytes:
    """Return ``sha256(b"cockpit-day-v1" || prev_day || merkle_root(chained_roots) || count as 8-byte big-endian)``.

    ``prev_day`` is :data:`GENESIS` for the first day, otherwise the previous day's root.
    A day with no batches still gets a root (its Merkle root is ``sha256(b"")``).

    Day ordering: ``chained_roots`` holds the chained root of every batch inserted that
    UTC day, across all model versions, sorted by ``(model_version, batch_seq)``. This
    function takes the list exactly as given and does not sort it; callers enforce the
    order, and a different order gives a different root.

    Raises ValueError if ``prev_day`` or any chained root is not 32 bytes, or
    ``chained_roots`` is not a list/tuple.
    """
    _require_hash(prev_day, "prev_day")
    roots = _require_sequence(chained_roots, "chained_roots")
    checked = [_require_hash(r, f"chained_roots[{i}]") for i, r in enumerate(roots)]
    return hashlib.sha256(_DAY_TAG + prev_day + merkle_root(checked) + len(checked).to_bytes(8, "big")).digest()
