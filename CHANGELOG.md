# Changelog

## 0.2.0

Every v0.1.0 record, row hash and Merkle root still verifies. A record with a paper price hashes exactly as it did in v0.1.0.

### Added

- Optional paper price and paper book on a prediction (Python and TypeScript). They come as a pair, are left out of the canonical bytes when absent (8 fields instead of 10), and are never `null`.
- `devig.estimator_probs` and `devig.devig_partial` (Python only): de-vig of a book that prices only part of a field, ported from GolfProject research.
- New module `consensus` (Python only): `consensus_close` implements rule `consensus-v1`, the mean of the reference books' de-vigged closing lines, rounded to 6 dp. A book counts when it prices at least 0.90 of the field, and a selection needs at least 2 books.
- Gate criteria: `clv_reference.consensus_rule` (`consensus-v1`) and a fixed `paper_price_rule` vocabulary (`hub_asof_best_at_batch_insert`).

### Changed

- TypeScript: `null` for `paperPrice` or `paperBook` is now a `TypeError` with the message "paperPrice must be absent (undefined), never null" (likewise for `paperBook`), and `undefined` now means absent rather than a type error.
- CI and release workflows run on `ubuntu-24.04` instead of `ubuntu-latest`.

### Breaking

- The gate-criteria schema is breaking: `clv_reference.consensus_rule` is required and `paper_price_rule` is a fixed vocabulary, so `validate_criteria` and `criteria_hash` reject every v0.1.0 criteria document.

## 0.1.0

First release.

- Odds conversion, de-vig, edge, Kelly and capped stake sizing, and (w, r) settlement with exact money math, in Python and TypeScript, tested against one shared fixtures file.
- Closing line value and gate statistics (Python).
- RFC 8785 canonical predictions, salted row hashes, RFC 6962 Merkle roots and inclusion proofs, and chained batch and day roots, in Python and TypeScript.
- Gate-criteria schema with `validate_criteria` and `criteria_hash` (Python).
- `cockpit-verify`, a bundle verifier that recomputes every hash, root, count and the chain against independent anchors (Python).
