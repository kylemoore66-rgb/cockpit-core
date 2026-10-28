/**
 * Canonical bytes for predictions: the TS twin of the Python package's `canonical.py`.
 *
 * Anyone can rebuild a published prediction's bytes in a browser and check its hash, so this must
 * produce exactly the bytes Python produces for every input Python accepts, and reject the rest:
 *
 * - Probabilities are strings at 6 decimal places and prices at 4, both rounded half-up. A number goes
 *   through `new Decimal(x)`, which reads the shortest round-trip digits (Python's `repr`). A string must
 *   match `^[0-9]+(\.[0-9]+)?$`. Output is always `toFixed`, never `toString` (no exponents, no dropped
 *   zeros). Like Python's 60-digit `quantize`, a value with more than 60 significant digits is rejected.
 * - Timestamps are `Date.prototype.toISOString()`: UTC, `YYYY-MM-DDTHH:MM:SS.mmmZ`, years 1 to 9999.
 * - Every string must be well-formed (no lone surrogates) and Unicode NFC.
 * - The 8 or 10 fields are serialised with RFC 8785 under the Python (snake_case) field names.
 * - `paperPrice` and `paperBook` are optional, but only as a pair: both given (10 fields, hashing exactly
 *   as in v0.1.0) or both absent (8 fields; the keys are left out, never written as null). `undefined` or
 *   a missing key is absent; `null` is a TypeError; exactly one of the pair is a RangeError.
 *
 * Errors: a value of the right JS type that is not acceptable is a RangeError; a value of the wrong JS
 * type (or a featuresSummary that is not a plain object) is a TypeError.
 */
import { Decimal as BaseDecimal } from "decimal.js";
import canonicalizeModule from "canonicalize";
import { Decimal, type DecimalInput } from "./decimal.js";
import { STRING_GRAMMAR, checkExponent, show } from "./_exact.js";

/** A prediction as published. Field names are camelCase here and snake_case in the canonical bytes. */
export type CanonicalPrediction = {
  modelVersion: string;
  sport: string;
  event: string;
  market: string;
  selection: string;
  fairProb: number | DecimalInput;
  paperPrice?: number | DecimalInput; // optional, but only together with paperBook
  paperBook?: string;
  predictedAt: Date;
  featuresSummary: Readonly<Record<string, string>>;
};

// `canonicalize` is CommonJS (`module.exports = fn`) with a `export default` typing. Node's ESM loader
// hands back the function itself, while TS and some bundlers expect it under `.default`; accept both.
type Canonicalize = (input: unknown) => string | undefined;
const canonicalize: Canonicalize =
  typeof canonicalizeModule === "function"
    ? (canonicalizeModule as Canonicalize)
    : (canonicalizeModule as unknown as { default: Canonicalize }).default;

/** Python's quantize runs at precision 60: a result with a longer coefficient is an error there. */
const QUANTIZE_PRECISION = 60;

function toDecimal(value: unknown, what: string): BaseDecimal {
  let d: BaseDecimal;
  if (typeof value === "number") {
    d = new Decimal(value); // shortest round-trip digits, as Python's Decimal(repr(x))
  } else if (typeof value === "string") {
    if (!STRING_GRAMMAR.test(value)) {
      throw new RangeError(`${what} string must match [0-9]+(.[0-9]+)?, got ${show(value)}`);
    }
    d = new Decimal(value);
  } else if (BaseDecimal.isDecimal(value)) {
    d = new Decimal(value as BaseDecimal);
  } else {
    throw new TypeError(`${what} must be a number, Decimal or decimal string, got ${show(value)}`);
  }
  if (!d.isFinite()) throw new RangeError(`${what} must be finite, got ${show(value)}`);
  checkExponent(what, d, value); // before toDecimalPlaces expands any digits
  return d;
}

/** Round half-up to `dp` places and render with exactly `dp` places, as Python's quantize + `:f`. */
function quantize(d: BaseDecimal, dp: number, what: string): { q: BaseDecimal; text: string } {
  const q = d.toDecimalPlaces(dp, BaseDecimal.ROUND_HALF_UP);
  const text = q.toFixed(dp);
  const coefficient = text.replace(/^-/, "").replace(".", "").replace(/^0+(?=.)/, "");
  if (coefficient.length > QUANTIZE_PRECISION) throw new RangeError(`${what} out of range: ${show(q.toFixed())}`);
  return { q, text };
}

/** Probability as a 6 dp half-up string. Must lie strictly between 0 and 1 after rounding. */
export function fmtProb(p: number | DecimalInput): string {
  const { q, text } = quantize(toDecimal(p, "probability"), 6, "probability");
  if (!(q.gt(0) && q.lt(1))) {
    throw new RangeError(`probability must be strictly between 0 and 1 at 6 dp, got ${show(p)}`);
  }
  return text;
}

/** Decimal odds as a 4 dp half-up string. Must be greater than 1 after rounding. */
export function fmtPrice(o: number | DecimalInput): string {
  const { q, text } = quantize(toDecimal(o, "price"), 4, "price");
  if (!q.gt(1)) throw new RangeError(`price must be greater than 1 at 4 dp, got ${show(o)}`);
  return text;
}

/** UTC timestamp as `YYYY-MM-DDTHH:MM:SS.mmmZ` (a JS Date is always UTC at millisecond precision). */
export function fmtTs(d: Date): string {
  if (!(d instanceof Date)) throw new TypeError(`timestamp must be a Date, got ${show(d)}`);
  const t = d.getTime();
  if (Number.isNaN(t)) throw new RangeError("timestamp is an invalid Date");
  const year = d.getUTCFullYear();
  if (year < 1 || year > 9999) throw new RangeError(`timestamp year must be 1 to 9999, got ${year}`);
  return d.toISOString();
}

const LONE_SURROGATE = /\p{Cs}/u;

function isWellFormed(s: string): boolean {
  const native = (s as { isWellFormed?: () => boolean }).isWellFormed;
  return typeof native === "function" ? native.call(s) : !LONE_SURROGATE.test(s);
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string") throw new TypeError(`${what} must be a string, got ${show(value)}`);
  if (!isWellFormed(value)) throw new RangeError(`${what} has a lone surrogate: ${JSON.stringify(value)}`);
  if (value.normalize("NFC") !== value) throw new RangeError(`${what} is not Unicode NFC: ${JSON.stringify(value)}`);
  return value;
}

function features(value: unknown): Record<string, string> {
  const proto = typeof value === "object" && value !== null ? Object.getPrototypeOf(value) : undefined;
  if (proto !== Object.prototype && proto !== null) {
    throw new TypeError(`featuresSummary must be a plain object of string to string, got ${show(value)}`);
  }
  // Object.fromEntries defines own properties, so a "__proto__" key is data, never the prototype.
  return Object.fromEntries(
    Object.entries(value as object).map(([k, v]) => [
      text(k, "featuresSummary key"),
      text(v, `featuresSummary[${JSON.stringify(k)}]`),
    ]),
  );
}

/**
 * RFC 8785 UTF-8 bytes of the canonical fields: 10 with the paper price and book, 8 without.
 * Throws on anything non-canonical, including only one of the paper pair.
 */
export function canonicalBytes(p: CanonicalPrediction): Uint8Array {
  if (typeof p !== "object" || p === null) throw new TypeError(`prediction must be an object, got ${show(p)}`);
  // Absent, never null: null is a wrong-type value, checked before the pair rule so it is never "absent".
  if (p.paperPrice === null) throw new TypeError("paperPrice must be absent (undefined), never null");
  if (p.paperBook === null) throw new TypeError("paperBook must be absent (undefined), never null");
  const hasPrice = p.paperPrice !== undefined;
  const hasBook = p.paperBook !== undefined;
  if (hasPrice !== hasBook) throw new RangeError("paperPrice and paperBook must be given together");
  const obj = Object.fromEntries([
    ["model_version", text(p.modelVersion, "modelVersion")],
    ["sport", text(p.sport, "sport")],
    ["event", text(p.event, "event")],
    ["market", text(p.market, "market")],
    ["selection", text(p.selection, "selection")],
    ["fair_prob", fmtProb(p.fairProb)],
    // Without the pair the keys are simply not there. Inline, so fields validate in the v0.1.0 order.
    ...(hasPrice
      ? [
          ["paper_price", fmtPrice(p.paperPrice as number | DecimalInput)],
          ["paper_book", text(p.paperBook, "paperBook")],
        ]
      : []),
    ["predicted_at", fmtTs(p.predictedAt)],
    ["features_summary", features(p.featuresSummary)],
  ]);
  const json = canonicalize(obj);
  if (json === undefined) throw new TypeError("canonicalize returned undefined");
  return new TextEncoder().encode(json);
}
