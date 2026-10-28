"""Test helper: writes real reveal bundles, and plays the forger who recomputes every root."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cockpit_core.canonical import CanonicalPrediction, canonical_bytes
from cockpit_core.proof import GENESIS, chain_root, merkle_root, row_hash


def _prediction(model_version: str, note: str, paper: bool = True) -> CanonicalPrediction:
    """A synthetic prediction; ``paper=False`` omits the paper price and book (a v0.2.0 record)."""
    return CanonicalPrediction(
        model_version=model_version,
        sport="golf",
        event="2026-mexico-open",
        market="2026-mexico-open:top_10",
        selection="2026-mexico-open:top_10:player-123",
        fair_prob=0.1834,
        paper_price="6.5" if paper else None,
        paper_book="draftkings" if paper else None,
        predicted_at=datetime(2026, 10, 29, 13, 5, tzinfo=UTC),
        features_summary={"note": note},
    )


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def _batch_records(rows: list[dict]) -> list[dict]:
    """Recompute every batch line (n_rows, merkle root, chain) from the rows given."""
    by_seq: dict[int, list[dict]] = {}
    for r in rows:
        by_seq.setdefault(r["batch_seq"], []).append(r)
    batches = []
    prev = GENESIS
    for seq in sorted(by_seq):
        ordered = sorted(by_seq[seq], key=lambda r: r["index"])
        root = merkle_root([bytes.fromhex(r["row_hash"]) for r in ordered])
        prev = chain_root(prev, root, len(ordered))
        batches.append(
            {"batch_seq": seq, "n_rows": len(ordered), "merkle_root": root.hex(), "chained_root": prev.hex()}
        )
    return batches


def write_bundle(
    tmp_path: Path, batches: list[list[str]], model_version: str = "golf-baseline@1", paper: bool = True
) -> tuple[Path, dict[int, str]]:
    """Write a true bundle (one batch per inner list, one row per note) and return it with its anchors.

    ``paper=False`` writes every row without a paper price and book.
    """
    path = tmp_path / "bundle"
    path.mkdir(parents=True)
    rows = []
    for seq, notes in enumerate(batches, start=1):
        for i, note in enumerate(notes):
            canonical = canonical_bytes(_prediction(model_version, note, paper))
            salt = bytes([seq, i]) * 8
            rows.append(
                {
                    "batch_seq": seq,
                    "index": i,
                    "canonical": canonical.decode("utf-8"),
                    "salt": salt.hex(),
                    "row_hash": row_hash(salt, canonical).hex(),
                }
            )
    batch_lines = _batch_records(rows)
    (path / "manifest.json").write_text(
        json.dumps({"model_version": model_version, "n_batches": len(batch_lines)}), encoding="utf-8"
    )
    write_jsonl(path / "rows.jsonl", rows)
    write_jsonl(path / "batches.jsonl", batch_lines)
    return path, {b["batch_seq"]: b["chained_root"] for b in batch_lines}


def rewrite_batches(path: Path) -> None:
    """The forger's move: renumber the remaining rows and recompute every batch line and the manifest."""
    rows = read_jsonl(path / "rows.jsonl")
    by_seq: dict[int, list[dict]] = {}
    for r in rows:
        by_seq.setdefault(r["batch_seq"], []).append(r)
    renumbered = []
    for seq in sorted(by_seq):
        for i, r in enumerate(sorted(by_seq[seq], key=lambda r: r["index"])):
            renumbered.append({**r, "index": i})
    batch_lines = _batch_records(renumbered)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    manifest["n_batches"] = len(batch_lines)
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    write_jsonl(path / "rows.jsonl", renumbered)
    write_jsonl(path / "batches.jsonl", batch_lines)
