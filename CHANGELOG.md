# Changelog

## 0.2.0

Every v0.1.0 record, row hash and Merkle root still verifies. A record with a paper price hashes exactly as it did in v0.1.0.

### Added

- Optional paper price and paper book on a prediction (Python and TypeScript). They come as a pair, are left out of the canonical bytes when absent (8 fields instead of 10), and are never `null`.
- `devig.estimator_probs` and `devig.devig_partial` (Python only): de-vig of a book that prices only part of a field, ported from GolfProject research.
- New module `consensus` (Python only): `consensus_close` implements rule `consensus-v1`: for each selection, the mean of the de-vigged closing lines of the reference books that cover the field and whose de-vig succeeds, rounded to 6 dp. A book counts when it prices at least 0.90 of the field (a book whose de-vig fails is dropped), and a selection needs at least 2 books. Non-finite odds from a reference book are rejected.
- De-vig input guards (Python): `devig_partial` refuses Shin with a `total` above 1 (it never switches method), and `estimator_probs` rejects an `n_winners` that is not a finite number greater than 0 (including `bool`, NaN and infinity).
- Gate criteria: `clv_reference.consensus_rule` (`consensus-v1`) and a fixed `paper_price_rule` vocabulary (`hub_asof_best_at_batch_insert`).

### Changed

- TypeScript: `null` for `paperPrice` or `paperBook` was already a `TypeError` in v0.1.0 and still is, now checked before any other field and with the message "paperPrice must be absent (undefined), never null" (likewise for `paperBook`). `undefined` (or a missing key) now means absent rather than a type error.
- TypeScript typing: `paperPrice` and `paperBook` are now optional properties of `CanonicalPrediction`. Strict TypeScript code that reads them as always present may no longer compile.
- Forward compatibility: a v0.1.0 `verify_bundle` (or any v0.1.0 consumer) rejects 8-key records, so records without a paper price need cockpit-core 0.2.0 or later to verify. Records with a paper price verify under both.
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
