import json
import time
from pathlib import Path

import rfc8785
from bundles import _prediction, read_jsonl, rewrite_batches, write_bundle, write_jsonl

from cockpit_core.canonical import canonical_bytes
from cockpit_core.proof import GENESIS, chain_root, merkle_root, row_hash
from cockpit_core.verify import VerifyReport, main, verify_bundle

NOTES = [["alpha", "bravo", "charlie"], ["delta"]]


def _write_anchors(tmp_path: Path, anchors: dict[int, str]) -> Path:
    f = tmp_path / "anchors.json"
    f.write_text(json.dumps({str(k): v for k, v in anchors.items()}), encoding="utf-8")
    return f


def _errors(report: VerifyReport) -> str:
    return "\n".join(report.errors)


def test_verify_valid_bundle(tmp_path):
    path, anchors = write_bundle(tmp_path, NOTES)
    report = verify_bundle(path, anchors)
    assert report.ok, report.errors
    assert report.anchored
    assert report.errors == []
    assert report.n_batches == 2
    assert report.n_rows == 4

    # independent recomputation of the chain over both batches
    prev = GENESIS
    for seq, notes in enumerate(NOTES, start=1):
        hashes = [
            row_hash(bytes([seq, i]) * 8, canonical_bytes(_prediction("golf-baseline@1", n)))
            for i, n in enumerate(notes)
        ]
        prev = chain_root(prev, merkle_root(hashes), len(hashes))
    assert report.final_chained_root == prev.hex()


def test_verify_without_anchors_is_unanchored(tmp_path, capsys):
    path, _ = write_bundle(tmp_path, NOTES)
    report = verify_bundle(path)
    assert report.ok, report.errors
    assert not report.anchored
    assert main([str(path)]) == 2
    assert "UNANCHORED: consistency only, not proof" in capsys.readouterr().out


def test_anchors_missing_final_batch_is_unanchored(tmp_path):
    path, anchors = write_bundle(tmp_path, NOTES)
    report = verify_bundle(path, {1: anchors[1]})
    assert report.ok, report.errors
    assert not report.anchored


def test_forged_bundle_fails_against_anchors(tmp_path):
    path, anchors = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    write_jsonl(path / "rows.jsonl", [r for r in rows if not (r["batch_seq"] == 1 and r["index"] == 1)])
    rewrite_batches(path)

    forged = verify_bundle(path)
    assert forged.ok, forged.errors  # consistency alone proves nothing
    assert forged.n_rows == 3

    checked = verify_bundle(path, anchors)
    assert not checked.ok
    assert not checked.anchored
    anchor_errors = [e for e in checked.errors if "anchor" in e]
    assert anchor_errors
    assert anchor_errors[0].startswith("batch 1:")


def test_anchor_for_unknown_batch_rejected(tmp_path):
    path, anchors = write_bundle(tmp_path, NOTES)
    report = verify_bundle(path, {**anchors, 3: "00" * 32})
    assert not report.ok
    assert "batch 3" in _errors(report)


def test_wrong_model_version_row_rejected(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    canonical = canonical_bytes(_prediction("golf-other@1", "alpha"))
    salt = bytes([1, 0]) * 8
    rows[0] = {**rows[0], "canonical": canonical.decode(), "row_hash": row_hash(salt, canonical).hex()}
    write_jsonl(path / "rows.jsonl", rows)
    rewrite_batches(path)

    report = verify_bundle(path)
    assert not report.ok
    assert "batch 1 row 0" in _errors(report)
    assert "model_version" in _errors(report)


def test_verify_detects_dropped_row(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    write_jsonl(path / "rows.jsonl", [r for r in rows if not (r["batch_seq"] == 1 and r["index"] == 1)])

    report = verify_bundle(path)
    assert not report.ok
    assert any(e.startswith("batch 1:") and "n_rows" in e for e in report.errors), report.errors


def test_verify_detects_dropped_last_row(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    write_jsonl(path / "rows.jsonl", [r for r in rows if not (r["batch_seq"] == 1 and r["index"] == 2)])

    report = verify_bundle(path)
    assert not report.ok
    assert any(e.startswith("batch 1:") and "n_rows" in e for e in report.errors), report.errors


def test_verify_detects_reordered_rows(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    rows[0]["index"], rows[1]["index"] = rows[1]["index"], rows[0]["index"]
    write_jsonl(path / "rows.jsonl", rows)

    report = verify_bundle(path)
    assert not report.ok
    assert any(e.startswith("batch 1:") and "merkle_root" in e for e in report.errors), report.errors


def test_file_order_does_not_matter(tmp_path):
    path, anchors = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    write_jsonl(path / "rows.jsonl", list(reversed(rows)))

    report = verify_bundle(path, anchors)
    assert report.ok, report.errors
    assert report.anchored


def test_verify_detects_duplicated_row(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    write_jsonl(path / "rows.jsonl", [*rows, rows[1]])

    report = verify_bundle(path)
    assert not report.ok
    assert any(e.startswith("batch 1:") for e in report.errors), report.errors


def test_verify_detects_tampered_canonical(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    rows[1]["canonical"] = rows[1]["canonical"].replace("bravo", "bravO")
    write_jsonl(path / "rows.jsonl", rows)

    report = verify_bundle(path)
    assert not report.ok
    assert any(e.startswith("batch 1 row 1:") and "row_hash" in e for e in report.errors), report.errors


def test_verify_detects_batch_gap(tmp_path):
    path, _ = write_bundle(tmp_path, [["a"], ["b"], ["c"]])
    write_jsonl(path / "rows.jsonl", [r for r in read_jsonl(path / "rows.jsonl") if r["batch_seq"] != 2])
    write_jsonl(path / "batches.jsonl", [b for b in read_jsonl(path / "batches.jsonl") if b["batch_seq"] != 2])
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    (path / "manifest.json").write_text(json.dumps({**manifest, "n_batches": 2}), encoding="utf-8")

    report = verify_bundle(path)
    assert not report.ok
    assert "batch_seq" in _errors(report)


def test_non_canonical_but_parseable_row_rejected(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    obj = json.loads(rows[0]["canonical"])
    obj["fair_prob"] = "0.18"
    canonical = rfc8785.dumps(obj)  # re-serialises cleanly, so only the shape check can catch it
    salt = bytes.fromhex(rows[0]["salt"])
    rows[0] = {**rows[0], "canonical": canonical.decode(), "row_hash": row_hash(salt, canonical).hex()}
    write_jsonl(path / "rows.jsonl", rows)
    rewrite_batches(path)

    report = verify_bundle(path)
    assert not report.ok
    assert any(e.startswith("batch 1 row 0:") and "fair_prob" in e for e in report.errors), report.errors


def test_non_rfc8785_serialisation_rejected(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    canonical = json.dumps(json.loads(rows[0]["canonical"]), indent=1).encode()  # same data, other bytes
    salt = bytes.fromhex(rows[0]["salt"])
    rows[0] = {**rows[0], "canonical": canonical.decode(), "row_hash": row_hash(salt, canonical).hex()}
    write_jsonl(path / "rows.jsonl", rows)
    rewrite_batches(path)

    report = verify_bundle(path)
    assert not report.ok
    assert any(e.startswith("batch 1 row 0:") and "re-canonical" in e for e in report.errors), report.errors


def test_line_separator_inside_a_note_is_one_row(tmp_path):
    # U+2028 is not a JSONL line break; splitting on it would invent a broken row
    path, anchors = write_bundle(tmp_path, [["one two", "x"]])
    report = verify_bundle(path, anchors)
    assert report.ok, report.errors
    assert report.n_rows == 2


def test_missing_manifest_and_malformed_lines(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    (path / "manifest.json").unlink()
    with (path / "rows.jsonl").open("a", encoding="utf-8") as f:
        f.write("{not json\n")

    report = verify_bundle(path)
    assert not report.ok
    text = _errors(report)
    assert "manifest" in text
    assert "rows.jsonl line 5" in text


def test_missing_bundle_directory(tmp_path):
    report = verify_bundle(tmp_path / "nope")
    assert not report.ok
    assert not report.anchored


def test_cli_exit_codes(tmp_path, capsys):
    path, anchors = write_bundle(tmp_path, NOTES)
    anchors_file = _write_anchors(tmp_path, anchors)
    assert main([str(path), "--anchors", str(anchors_file)]) == 0
    assert main([str(path)]) == 2

    rows = read_jsonl(path / "rows.jsonl")
    rows[0]["canonical"] = rows[0]["canonical"].replace("alpha", "alphA")
    write_jsonl(path / "rows.jsonl", rows)
    assert main([str(path), "--anchors", str(anchors_file)]) == 1
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "batch 1 row 0" in out


def test_cli_bad_anchors_file_and_usage_errors_exit_1(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    bad = tmp_path / "bad.json"
    bad.write_text('{"one": "zz"}', encoding="utf-8")
    assert main([str(path), "--anchors", str(bad)]) == 1
    assert main([str(path), "--anchors", str(tmp_path / "missing.json")]) == 1
    assert main([]) == 1  # never 2: 2 means "consistent but unanchored"


def test_hostile_row_index_fails_fast_with_bounded_message(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    rows[1]["index"] = 10**18
    write_jsonl(path / "rows.jsonl", rows)

    start = time.perf_counter()
    report = verify_bundle(path)
    assert time.perf_counter() - start < 2
    assert not report.ok
    assert any(e.startswith("batch 1:") and "index" in e for e in report.errors), report.errors
    assert len(_errors(report)) < 5000


def test_row_index_beyond_u64_rejected_at_parse(tmp_path):
    path, _ = write_bundle(tmp_path, NOTES)
    rows = read_jsonl(path / "rows.jsonl")
    rows[1]["index"] = 2**64
    write_jsonl(path / "rows.jsonl", rows)

    report = verify_bundle(path)
    assert not report.ok
    assert "rows.jsonl line 2" in _errors(report)
    assert len(_errors(report)) < 5000


def test_many_bad_indexes_message_is_capped(tmp_path):
    path, _ = write_bundle(tmp_path, [[str(i) for i in range(60)]])
    rows = read_jsonl(path / "rows.jsonl")
    for r in rows:
        r["index"] = 0  # 60 duplicates, 59 missing
    write_jsonl(path / "rows.jsonl", rows)

    report = verify_bundle(path)
    assert not report.ok
    index_errors = [e for e in report.errors if "indexes" in e]
    assert len(index_errors) == 1
    assert "..." in index_errors[0]
    assert len(index_errors[0]) < 600


def test_truncated_bundle_fails_against_later_anchors(tmp_path, capsys):
    _, true_anchors = write_bundle(tmp_path / "full", [["a"], ["b"], ["c"]])
    truncated, _ = write_bundle(tmp_path / "cut", [["a"], ["b"]])  # correctly rebuilt, batch 3 withheld

    report = verify_bundle(truncated, true_anchors)
    assert not report.ok
    assert not report.anchored
    assert any(e.startswith("batch 3:") for e in report.errors), report.errors

    anchors_file = _write_anchors(tmp_path, true_anchors)
    assert main([str(truncated), "--anchors", str(anchors_file)]) == 1
    out = capsys.readouterr().out
    assert "anchored: no" in out
    assert "batch 3" in out


def test_failed_bundle_is_never_anchored(tmp_path):
    path, anchors = write_bundle(tmp_path, NOTES)
    with (path / "rows.jsonl").open("a", encoding="utf-8") as f:
        f.write("{not json\n")  # a failure that leaves the recomputed chain matching every anchor

    report = verify_bundle(path, anchors)
    assert not report.ok
    assert not report.anchored
