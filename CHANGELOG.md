# Changelog

## 0.3.0

Every v0.1.0 and v0.2.0 record, row hash and Merkle root still verifies. There are no breaking changes: everything below is new, and no existing function, fixture value or canonical byte changed.

### Added

- New module `live` (Python only): `live_fair` implements rule `consensus-loo-v1`, the live leave-one-out consensus. The book being priced (`exclude`) is left out, and every other book that prices the whole market is de-vigged to 1 (method `power` unless told otherwise); a selection's fair probability is the mean of those books, rounded to 6 dp by `fmt_prob`. At least 3 such books are needed (`min_books`, default `LIVE_MIN_BOOKS`), otherwise it returns `None`. It returns a `LiveFair` with the fair probabilities, the contributing books, the rule and the method. Books are processed in code-point order, so the digits do not depend on input order. The caller contract is one market per call: the field is every selection any book in `quotes` prices, so a book quoting a selection that no other book prices leaves no book counting and the result is `None` for every `exclude`. Because of the 6 dp rounding the probabilities sum to 1 only within about `len(fair) * 5e-7`. Bad input (an unknown method, `min_books` below 1 or a `bool`, a bad `exclude`, odds that are not finite and above 1 in any book, the excluded one included) raises `ValueError` before any work.
- New module `expected` (Python and TypeScript): `expected_profit` (stake * (p * o - 1)), `profit_variance` (stake^2 * o^2 * p(1 - p)), `outcome_moments` (mean and variance of profit over settled outcomes, so pushes, half wins and dead heats count; the probabilities must sum to exactly 1) and `cumulative_band` (running sum of expected profit, and `sigma`, the square root of the running sum of variance, for the Results band). The money values are exact, divided once at precision 40 (truncated) and never rounded: round for display only. The running expected profit in `cumulative_band` is exact; `sigma` is a float, the same double in both languages. The TypeScript names are `expectedProfit`, `profitVariance`, `outcomeMoments`, `cumulativeBand` and the `BandPoint` type.
- `odds.price_decimal_from_american` / `priceDecimalFromAmerican` (Python and TypeScript): the bet-price storage rule. American odds to the decimal price, computed exactly and rounded half-up to exactly 8 dp (`-51200` stores as `1.00195313`), the same rule the database applies. It refuses `-100` (normalise it to `+100`), any `|a| < 100`, and anything that is not an integer. `decimal_from_american` is unchanged (precision 40, truncated).
- New module `pm` (Python only): `pm_break_even` is the win probability at which buying C contracts at price p breaks even once the taker fee is paid, (p * C + fee) / C, with fee = rate * C * p(1 - p) rounded once per order onto the venue's grid. The fee is exact and the result is divided once at precision 40 (truncated), not rounded. Fee models are versioned in `FEE_MODELS` (read-only): `kalshi-taker-2026-11` (rate 0.07, rounded up to $0.0001) and `polymarket-2026-11` (rate 0.05, rounded down to 5 dp). A code never changes once released; a fee change adds a new code. An unknown code raises `KeyError`. Scope: the Kalshi model is the general taker fee (multiplier 1) of a direct member, one order at one price; the Polymarket model is the Other / General taker rate. Maker fees, other Kalshi multipliers, FCM-cleared accounts (their balances sit on the $0.01 grid) and Polymarket's other category rates are not modelled. Both venues' rules were read on 2026-11-02; Polymarket's page does not name the rounding direction, and rounding down is the reading under which fees below 0.00001 round to zero. `FeeModel` also supports a `ceil_cent` rounding for a future model.
- TypeScript settlement constants `WIN`, `LOSS`, `VOID`, `HALF_WIN` and `HALF_LOSS`, the same fractions as Python's `settle` constants, frozen and equal to what `settlement()` returns for them.

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
