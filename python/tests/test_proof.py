import hashlib
from datetime import datetime

import pytest

from cockpit_core.canonical import CanonicalPrediction, canonical_bytes
from cockpit_core.proof import (
    GENESIS,
    chain_root,
    day_root,
    inclusion_proof,
    merkle_root,
    new_salt,
    row_hash,
    verify_inclusion,
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


def _leaves(strings: list[str]) -> list[bytes]:
    return [s.encode("utf-8") for s in strings]


def _flip(b: bytes) -> bytes:
    return bytes([b[0] ^ 0x01]) + b[1:]


# --- constants and salts -------------------------------------------------------------


def test_genesis_is_32_zero_bytes():
    assert GENESIS == bytes(32)


def test_new_salt_is_16_random_bytes():
    a, b = new_salt(), new_salt()
    assert isinstance(a, bytes)
    assert len(a) == 16
    assert a != b


# --- row hashes ----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["basic", "unicode", "millis"])
def test_row_hash_matches_fixture(cases, name):
    fx = cases["canonical"][name]
    canonical = canonical_bytes(_build(fx["prediction"]))
    assert canonical == fx["canonical"].encode("utf-8")
    assert row_hash(bytes.fromhex(fx["salt_hex"]), canonical).hex() == fx["row_hash"]


def test_row_hash_is_sha256_of_salt_then_canonical():
    salt = bytes(range(16))
    assert row_hash(salt, b"x") == hashlib.sha256(salt + b"x").digest()


@pytest.mark.parametrize("salt", [b"", bytes(15), bytes(17), bytes(32)])
def test_short_salt_rejected(salt):
    with pytest.raises(ValueError):
        row_hash(salt, b"{}")


@pytest.mark.parametrize(("salt", "canonical"), [("0" * 16, b"{}"), (bytes(16), "{}"), (bytes(16), None)])
def test_row_hash_rejects_non_bytes(salt, canonical):
    with pytest.raises(ValueError):
        row_hash(salt, canonical)


# --- Merkle roots --------------------------------------------------------------------


def test_merkle_roots_match_fixture(cases):
    for fx in cases["merkle"]["roots"]:
        assert merkle_root(_leaves(fx["leaves"])).hex() == fx["root"], fx["leaves"]


def test_merkle_root_of_empty_tree_is_sha256_of_nothing():
    assert merkle_root([]) == hashlib.sha256(b"").digest()


def test_merkle_root_follows_rfc6962_shape():
    def leaf(d: bytes) -> bytes:
        return hashlib.sha256(b"\x00" + d).digest()

    def node(left: bytes, right: bytes) -> bytes:
        return hashlib.sha256(b"\x01" + left + right).digest()

    a, b, c, d, e = (leaf(x) for x in _leaves(["a", "b", "c", "d", "e"]))
    # n=5 splits at k=4: left is the full 4-leaf tree, right is the lone 5th leaf.
    assert merkle_root(_leaves(["a", "b", "c", "d", "e"])) == node(node(node(a, b), node(c, d)), e)
    # n=3 splits at k=2.
    assert merkle_root(_leaves(["a", "b", "c"])) == node(node(a, b), c)


@pytest.mark.parametrize("bad", [["a"], [b"a", "b"], [None], "ab", b"ab"])
def test_merkle_root_rejects_non_bytes_leaves(bad):
    with pytest.raises(ValueError):
        merkle_root(bad)


# --- inclusion proofs ----------------------------------------------------------------


def test_inclusion_proof_matches_fixture(cases):
    fx = cases["merkle"]["inclusion"]
    leaves = _leaves(fx["leaves"])
    proof = inclusion_proof(leaves, fx["index"])
    assert [p.hex() for p in proof] == fx["proof"]

    root = merkle_root(leaves)
    n = len(leaves)
    assert verify_inclusion(leaves[fx["index"]], fx["index"], n, proof, root) is True

    # Any single tampered proof element fails.
    for i in range(len(proof)):
        tampered = list(proof)
        tampered[i] = _flip(tampered[i])
        assert verify_inclusion(leaves[fx["index"]], fx["index"], n, tampered, root) is False
    # Any other index fails, as does an out-of-range one.
    for idx in [*range(n), n, n + 1, -1]:
        if idx != fx["index"]:
            assert verify_inclusion(leaves[fx["index"]], idx, n, proof, root) is False


def test_verify_inclusion_rejects_wrong_leaf_size_root_and_lengths(cases):
    fx = cases["merkle"]["inclusion"]
    leaves = _leaves(fx["leaves"])
    i, n = fx["index"], len(leaves)
    proof = inclusion_proof(leaves, i)
    root = merkle_root(leaves)
    assert verify_inclusion(b"z", i, n, proof, root) is False
    assert verify_inclusion(leaves[i], i, n, proof, _flip(root)) is False
    assert verify_inclusion(leaves[i], i, n - 1, proof, root) is False
    assert verify_inclusion(leaves[i], i, 0, proof, root) is False
    assert verify_inclusion(leaves[i], i, -1, proof, root) is False
    assert verify_inclusion(leaves[i], i, n, proof[:-1], root) is False
    assert verify_inclusion(leaves[i], i, n, [*proof, proof[0]], root) is False
    assert verify_inclusion(leaves[i], i, n, [], root) is False
    assert verify_inclusion(leaves[i], i, n, list(reversed(proof)), root) is False
    # A proof element of the wrong size is a bad proof, not a crash.
    assert verify_inclusion(leaves[i], i, n, [proof[0][:31], *proof[1:]], root) is False
    assert verify_inclusion(leaves[i], i, n, [proof[0] + b"\x00", *proof[1:]], root) is False


def test_root_alone_does_not_commit_tree_size(cases):
    """RFC 9162 behaviour, pinned so nobody relies on the opposite.

    Leaf 2 has the same path shape in trees of 5 and 6 leaves (the last proof element is
    just "the right subtree"), so the proof also verifies with tree_size=6. The size must
    be bound elsewhere: chain_root commits n_rows next to the batch root.
    """
    fx = cases["merkle"]["inclusion"]
    leaves = _leaves(fx["leaves"])
    i, n = fx["index"], len(leaves)
    proof = inclusion_proof(leaves, i)
    assert verify_inclusion(leaves[i], i, n + 1, proof, merkle_root(leaves)) is True


@pytest.mark.parametrize("n", range(1, 18))
def test_inclusion_proof_round_trips_for_every_index(n):
    leaves = [f"leaf-{j}".encode() for j in range(n)]
    root = merkle_root(leaves)
    for i in range(n):
        proof = inclusion_proof(leaves, i)
        assert verify_inclusion(leaves[i], i, n, proof, root) is True
        for j in range(n):
            if j != i:
                assert verify_inclusion(leaves[i], j, n, proof, root) is False
                assert verify_inclusion(leaves[j], i, n, proof, root) is False


def test_single_leaf_tree_has_empty_proof():
    root = merkle_root([b"only"])
    assert inclusion_proof([b"only"], 0) == []
    assert verify_inclusion(b"only", 0, 1, [], root) is True
    assert verify_inclusion(b"only", 0, 1, [root], root) is False


@pytest.mark.parametrize("index", [-1, 5, 6, True, 2.0, "2", None])
def test_inclusion_proof_rejects_bad_index(index):
    with pytest.raises(ValueError):
        inclusion_proof(_leaves(["a", "b", "c", "d", "e"]), index)


def test_inclusion_proof_rejects_empty_tree():
    with pytest.raises(ValueError):
        inclusion_proof([], 0)


@pytest.mark.parametrize(
    "args",
    [
        ("a", 0, 1, [], bytes(32)),  # leaf is str, not bytes
        (b"a", True, 1, [], bytes(32)),  # index is bool
        (b"a", 0, 1.0, [], bytes(32)),  # tree_size is float
        (b"a", 0, 1, ["00" * 32], bytes(32)),  # proof element is str
        (b"a", 0, 1, b"\x00" * 32, bytes(32)),  # proof is bytes, not a sequence of hashes
        (b"a", 0, 1, [], bytes(31)),  # root is not 32 bytes
        (b"a", 0, 1, [], "00" * 32),  # root is str
    ],
)
def test_verify_inclusion_raises_only_for_invalid_argument_types(args):
    with pytest.raises(ValueError):
        verify_inclusion(*args)


# --- chained batch roots and day roots -----------------------------------------------


def test_chain_and_day_roots_match_fixture(cases):
    prev = None
    for fx in cases["merkle"]["chain"]:
        start = GENESIS if fx["prev"] == "genesis" else prev
        assert fx["prev"] in {"genesis", "previous"}
        assert start is not None
        batch = merkle_root(_leaves(fx["batch_leaves"]))
        prev = chain_root(start, batch, fx["n_rows"])
        assert prev.hex() == fx["chained"]

    prev = None
    for fx in cases["merkle"]["day"]:
        start = GENESIS if fx["prev"] == "genesis" else prev
        assert fx["prev"] in {"genesis", "previous"}
        assert start is not None
        prev = day_root(start, [bytes.fromhex(h) for h in fx["chained_roots"]])
        assert prev.hex() == fx["day_root"]


def test_chain_and_day_root_formulas():
    prev, batch = bytes(range(32)), bytes(range(32, 64))
    assert (
        chain_root(prev, batch, 3)
        == hashlib.sha256(b"cockpit-chain-v1" + prev + batch + (3).to_bytes(8, "big")).digest()
    )
    roots = [bytes([7]) * 32, bytes([9]) * 32]
    assert (
        day_root(prev, roots)
        == hashlib.sha256(b"cockpit-day-v1" + prev + merkle_root(roots) + (2).to_bytes(8, "big")).digest()
    )


def test_day_root_order_matters():
    a, b = bytes([1]) * 32, bytes([2]) * 32
    assert day_root(GENESIS, [a, b]) != day_root(GENESIS, [b, a])


@pytest.mark.parametrize(
    ("prev", "batch", "n_rows"),
    [
        (bytes(31), bytes(32), 1),
        (bytes(32), bytes(33), 1),
        ("00" * 32, bytes(32), 1),
        (bytes(32), bytes(32), -1),
        (bytes(32), bytes(32), 2**64),
        (bytes(32), bytes(32), True),
        (bytes(32), bytes(32), 1.0),
    ],
)
def test_chain_root_rejects_bad_inputs(prev, batch, n_rows):
    with pytest.raises(ValueError):
        chain_root(prev, batch, n_rows)


@pytest.mark.parametrize(
    ("prev", "roots"),
    [
        (bytes(31), []),
        ("00" * 32, []),
        (bytes(32), [bytes(31)]),
        (bytes(32), [bytes(32), "00" * 32]),
        (bytes(32), bytes(64)),
    ],
)
def test_day_root_rejects_bad_inputs(prev, roots):
    with pytest.raises(ValueError):
        day_root(prev, roots)
