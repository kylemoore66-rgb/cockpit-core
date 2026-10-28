# cockpit-core

The shared betting math and track-record proof code behind Cockpit, in Python (`python/`) and TypeScript (`ts/`). It is public so anyone can audit how Cockpit computes its edges, stakes and track record: the odds conversion, de-vigging, Kelly staking, settlement, and the hash-committed prediction log that proves a record was not edited after the fact. Both packages are tested against one shared file of hand-worked reference values (`fixtures/cases.json`), so the two implementations cannot silently disagree. To run the tests: `cd python && uv sync && uv run pytest` and `cd ts && npm ci && npm test`.

## Install

Nothing is published to PyPI or npm; install from the tagged GitHub release.

Python:

```
cockpit-core @ git+https://github.com/kylemoore66-rgb/cockpit-core@v0.2.0#subdirectory=python
```

TypeScript (release tarball):

```
https://github.com/kylemoore66-rgb/cockpit-core/releases/download/v0.2.0/kylemoore66-rgb-cockpit-core-0.2.0.tgz
```

## Scope

The Python package (imported as `cockpit_core`, Python 3.13+) is the full library. The TypeScript package (`@kylemoore66-rgb/cockpit-core`, Node 20+) carries only what a browser needs to recompute and check published numbers: odds, Kelly, settlement, canonical bytes and proofs.

| Area | Python module | TypeScript |
|---|---|---|
| Odds: implied probability, American/decimal conversion | `odds` | `implied`, `decimalFromAmerican`, `americanFromDecimal` |
| Kelly: edge, full Kelly, capped stake sizing | `kelly` | `edge`, `fullKelly`, `sizeStake` |
| Settlement and profit | `settle` | `settlement`, `profit` |
| Canonical bytes of a prediction | `canonical` | `fmtProb`, `fmtPrice`, `fmtTs`, `canonicalBytes` |
| Proofs: row hash, RFC 6962 Merkle root and inclusion proofs, chain and day roots | `proof` | `rowHash`, `merkleRoot`, `inclusionProof`, `verifyInclusion`, `chainRoot`, `dayRoot` |
| De-vig, statistics, closing line value (`devig` also has `estimator_probs` and `devig_partial` for books that price only part of a field) | `devig`, `stats`, `clv` | Python only |
| Consensus close (`consensus_close`) | `consensus` | Python only |
| Gate criteria (`validate_criteria`, `criteria_hash`); `clv_reference.consensus_rule` is required and `paper_price_rule` is a fixed vocabulary, so v0.1.0 criteria documents are rejected | `gate` | Python only |
| Bundle verifier (`verify_bundle`, `cockpit-verify`) | `verify` | Python only |
| `new_salt`, `to_canonical_time` | `proof`, `canonical` | Python only |

A prediction's paper price and paper book are optional, and they come as a pair. When absent they are left out of the canonical bytes entirely (the keys are not there). In TypeScript pass `undefined` (or omit the keys); `null` is a `TypeError`. In Python pass `None` for both, which means absent. Neither language ever writes `null` into the canonical bytes, and a half pair (one without the other) is an error in both. A record with a paper price hashes exactly as it did in v0.1.0, and every v0.1.0 record, row hash and Merkle root still verifies.

## Money and domain limits

Money is exact in both languages. Python takes and returns `Decimal` and computes with `Fraction`; TypeScript takes decimal.js `Decimal`s (or plain decimal strings) and computes with bigint rationals. Profit and stake are divided once at the end (precision 40, truncated; widened only for results of 1e36 or more so the cents survive), then profit rounds half-up (away from zero) and stakes round down, to cents.

Both packages enforce the same domain, asserted by the `domain_limits` fixtures:

- Every value entering money math (bankroll, stake, exposures, prices, the stake settings, the probability given to `size_stake`) must satisfy `|x| < 1e30`.
- No non-zero value entering money math or `fmt_prob`/`fmt_price` may have its leading digit beyond `10**60` or below `10**-60`. This is checked on the exponent alone, before any digits are expanded, so `1e-100000000` is rejected at once. Zero is zero whatever its exponent.
- Error messages echo at most about 40 characters of the offending value.

## Error contract

Bad input raises; it never returns a number. A bad **value** is `ValueError` in Python and `RangeError` in TypeScript. Wrong **types** differ, exactly as follows.

Python:

- `TypeError` is deliberate in only a few places: `size_stake(settings=...)` given something that is not a `StakeSettings`, `profit`/`unit_profit` given a settlement that is not a `Settlement`, and `stats.holm` given a bare string for `family` (it must be a collection of candidate names). Everywhere else in the money, canonical and proof functions, a wrong type is a `ValueError`. One incidental case: `matchup_settlement` given ranks that are not a sequence at all (for example `None`) raises whatever `len()` raises, a `TypeError`, rather than a checked `ValueError`.
- `ValueError` for every other wrong type the money, canonical and proof functions check: non-`Decimal` money values (including `StakeSettings` fields), non-numbers in the float helpers (`implied`, `edge`, `full_kelly`, `unit_profit`'s price), non-integers in `decimal_from_american`, `Settlement` fields, `dead_heat` counts, `matchup_settlement`'s rule, pick and each rank, `tie_rule_from_text`, every `CanonicalPrediction` field and `fmt_*` argument, and every `proof` argument.
- `canonical_bytes` raises `ValueError` for a half pair: a `paper_price` without a `paper_book`, or a `paper_book` without a `paper_price`. `None` for both means absent.
- `gate`: invalid criteria raise `jsonschema.ValidationError`; a non-NFC string anywhere in the criteria raises `ValueError`. Since v0.2.0 this includes every v0.1.0 criteria document: `clv_reference.consensus_rule` is required (`consensus-v1`) and `paper_price_rule` must be `hub_asof_best_at_batch_insert`.
- `consensus_close` raises `ValueError`, before doing any work, for: an unknown `rule` or de-vig method; Shin with `n_winners != 1`; an `n_winners` that is not an `int` of at least 1 (a `bool` is rejected); `reference_books` given as a bare string or as anything that is not a sequence; fewer than 2 distinct non-empty `reference_books`, or a reference book that is not a non-empty string; `closes` that is not a mapping, or a reference book's closes that are not a mapping; a selection key that is not a string; and odds that are not finite decimal odds greater than 1 (an infinite price is rejected). Only the reference books' closes are read or checked.
- In the `devig` module, `ValueError` is also raised for `devig_partial` with Shin and a `total` above 1 (Shin is single-winner, so it refuses rather than switching method), and for `estimator_probs` given an `n_winners` that is not a finite number greater than 0 (a `bool`, a non-number, NaN or infinity, zero or a negative), or Shin with `n_winners != 1`.
- Python never raises `decimal.InvalidOperation` (or any other `decimal` signal) from a public function, whatever the caller's decimal context.

TypeScript:

- `TypeError` for a wrong JS type in `canonical` (`fmtProb`/`fmtPrice` given anything but a number, string or Decimal; `fmtTs` given a non-`Date`; non-string text fields; a `featuresSummary` that is not a plain object; a prediction that is not an object) and in `proof` (not a `Uint8Array`, not a number or bigint, not an array); for `sizeStake` called without an object holding all its arguments, or with `settings` that is not an object holding all four settings; for `settlement()` given a non-string; and for `profit` given a settlement that is not `{ win: [n, d], refund: [n, d] }` of bigints.
- `paperPrice` and `paperBook` must be absent (`undefined`), never `null`: `null` is a `TypeError` ("…must be absent (undefined), never null"), and `undefined` means absent.
- `RangeError` for a wrong JS type in a money value (`sizeStake`, `profit`, `americanFromDecimal`, the stake settings: a JS number, boolean or `null` instead of a `Decimal` or decimal string) and in the float helpers (`implied`, `edge`, `fullKelly`, `decimalFromAmerican`), as well as for every bad value.

## Documented differences between the packages

These are deliberate, and pinned by tests:

- `implied(Infinity)` throws a `RangeError` in TypeScript; Python's `implied(float("inf"))` returns `0.0` (kept for the golf code it was ported from). TypeScript rejects an infinite price everywhere. Python rejects it in `edge`, `full_kelly`, `unit_profit`, every `Decimal` money function, `fmt_price` and `consensus_close`. Python's `devig`, `estimator_probs`, `devig_partial` and `clv` do not check for it yet (a known gap, not a deliberate difference): the de-vig functions treat an infinite price as implied probability 0 and `clv` returns infinity, so pass them finite odds only.
- Always serialise a decimal.js value with `toFixed` (`toFixed(2)` for money), never `toString`: decimal.js switches to exponent notation for large and small values, and canonical strings never contain exponents.
- TypeScript American odds are limited to safe integers (`decimalFromAmerican`'s input and `americanFromDecimal`'s result); Python takes and returns any `int`.
- TypeScript money functions also accept plain decimal strings matching `^[0-9]+(\.[0-9]+)?$` (no sign, exponent, whitespace or underscores); Python money functions require `Decimal`.

## Verifying a track record: `cockpit-verify`

```
cockpit-verify <bundle-dir> [--anchors anchors.json]
```

The bundle directory holds `manifest.json`, `rows.jsonl` and `batches.jsonl`. `anchors.json` maps batch numbers to the chained roots recorded independently at the time: `{"<batch_seq>": "<chained root hex>"}`. The verifier recomputes every row hash, every batch Merkle root, every row count and the whole chain, then compares the chain with the anchors.

| Exit code | Meaning |
|---|---|
| 0 | Proven: the bundle is consistent and the final batch's chained root matches its anchor. |
| 2 | Consistent but unanchored: the bundle agrees with itself, which a forger can also achieve. Not proof. |
| 1 | Failed: an inconsistency, an anchor mismatch, an unusable anchors file, or a usage error. |

Limit: anchors only prove what they cover. If the anchors given stop at batch k, a bundle truncated to batches 1..k (with later batches withheld) verifies as proven. The latest anchor must therefore come from independently fetched receipts, never from the bundle's owner.
