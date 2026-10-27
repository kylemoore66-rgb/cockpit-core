/**
 * Private helpers for exact money arithmetic (the TS twin of the Python package's `_exact.py`).
 *
 * Every money input becomes an exact rational of bigints. Profit and stake are built as one numerator
 * and one denominator with no rounding at all, then divided ONCE by decimal.js at precision 40,
 * truncated (ROUND_DOWN), exactly as the Python package does. Truncation never moves a value across a
 * cent or half-cent boundary, so the final rounding to cents sees the same side of every boundary as
 * the exact value does.
 */
import { Decimal as BaseDecimal } from "decimal.js";
import { Decimal } from "./decimal.js";

/** An exact rational n / d with d > 0 (not necessarily reduced). */
export type Rational = { readonly n: bigint; readonly d: bigint };

export const DIVISION_PRECISION = 40;

// Shared domain limits (the Python package enforces the same ones, asserted by the `domain_limits` fixtures).
/** A money input must satisfy |x| < 1e30, i.e. a leading digit (decimal.js `e`) below 30. */
export const MONEY_EXPONENT_LIMIT = 30;
/** No non-zero input may have its leading digit beyond 10**60 or below 10**-60. */
export const MAX_EXPONENT = 60;
const SHOWN_CHARS = 40;

const Div = BaseDecimal.clone({ precision: DIVISION_PRECISION, rounding: BaseDecimal.ROUND_DOWN });

export const STRING_GRAMMAR = /^[0-9]+(\.[0-9]+)?$/;
const SIGNED_GRAMMAR = /^(-?)([0-9]+)(?:\.([0-9]+))?$/;

export const ZERO: Rational = { n: 0n, d: 1n };
export const ONE: Rational = { n: 1n, d: 1n };

function fromPlain(text: string): Rational {
  const m = SIGNED_GRAMMAR.exec(text);
  if (m === null) throw new RangeError(`not a plain decimal: ${JSON.stringify(text)}`);
  const [, sign, whole, frac = ""] = m;
  const n = BigInt(whole + frac);
  return { n: sign === "-" ? -n : n, d: 10n ** BigInt(frac.length) };
}

/** A short rendering of `value` for error messages, cut to about 40 characters. */
export function show(value: unknown): string {
  let text: string;
  if (typeof value === "string") text = JSON.stringify(value);
  else if (typeof value === "bigint") text = `${value}n`;
  else if (BaseDecimal.isDecimal(value)) text = `Decimal(${(value as BaseDecimal).toString()})`;
  else text = String(value);
  return text.length <= SHOWN_CHARS ? text : `${text.slice(0, SHOWN_CHARS)}...`;
}

/**
 * Reject a finite non-zero Decimal whose leading digit lies beyond 10**60 or below 10**-60. Reads only
 * the exponent (`e`), never the digits, so 1e-100000000 fails at once. Zero is zero whatever its exponent.
 */
export function checkExponent(name: string, dec: BaseDecimal, value: unknown): void {
  if (!dec.isZero() && (dec.e < -MAX_EXPONENT || dec.e > MAX_EXPONENT)) {
    throw new RangeError(`${name} is out of range (decimal exponent beyond +/-${MAX_EXPONENT}), got ${show(value)}`);
  }
}

/** The money domain: |x| < 1e30, and the exponent limit above. Checked before any digits are expanded. */
function checkMoneyRange(name: string, dec: BaseDecimal, value: unknown): void {
  if (!dec.isZero() && dec.e >= MONEY_EXPONENT_LIMIT) {
    throw new RangeError(`${name} must be less than 1e${MONEY_EXPONENT_LIMIT} in magnitude, got ${show(value)}`);
  }
  checkExponent(name, dec, value);
}

/**
 * Exact rational of a finite decimal.js Decimal, or of a string matching `^[0-9]+(\.[0-9]+)?$`, inside
 * the money domain: |x| < 1e30, and a non-zero value no smaller than 1e-60 in magnitude (both checked on
 * the exponent before any digits are expanded). Anything else (number, bigint, boolean, null, NaN,
 * Infinity, exponent or signed strings, out-of-range values) is a RangeError, mirroring the Python
 * package's ValueError.
 */
export function exactMoney(name: string, value: unknown): Rational {
  if (typeof value === "string") {
    if (!STRING_GRAMMAR.test(value)) {
      throw new RangeError(`${name} must be a plain non-negative decimal string, got ${show(value)}`);
    }
    checkMoneyRange(name, new BaseDecimal(value), value); // the constructor never rounds
    return fromPlain(value);
  }
  if (BaseDecimal.isDecimal(value)) {
    const dec = value as BaseDecimal;
    if (!dec.isFinite()) throw new RangeError(`${name} must be a finite Decimal, got ${show(value)}`);
    checkMoneyRange(name, dec, value);
    return fromPlain(dec.toFixed()); // toFixed() with no argument is exact, in plain notation
  }
  throw new RangeError(`${name} must be a finite Decimal or a decimal string, got ${show(value)}`);
}

export const rat = (n: bigint, d: bigint = 1n): Rational => {
  if (d === 0n) throw new RangeError("zero denominator");
  return d < 0n ? { n: -n, d: -d } : { n, d };
};
export const add = (a: Rational, b: Rational): Rational => ({ n: a.n * b.d + b.n * a.d, d: a.d * b.d });
export const sub = (a: Rational, b: Rational): Rational => ({ n: a.n * b.d - b.n * a.d, d: a.d * b.d });
export const mul = (a: Rational, b: Rational): Rational => ({ n: a.n * b.n, d: a.d * b.d });
export const div = (a: Rational, b: Rational): Rational => rat(a.n * b.d, a.d * b.n);

/** Sign of a - b (-1, 0 or 1); exact, by cross-multiplication (denominators are positive). */
export function cmp(a: Rational, b: Rational): -1 | 0 | 1 {
  const l = a.n * b.d;
  const r = b.n * a.d;
  return l < r ? -1 : l > r ? 1 : 0;
}

export const min = (first: Rational, ...rest: Rational[]): Rational =>
  rest.reduce((m, x) => (cmp(x, m) < 0 ? x : m), first);
export const max = (first: Rational, ...rest: Rational[]): Rational =>
  rest.reduce((m, x) => (cmp(x, m) > 0 ? x : m), first);

/** The single division: n / d at `precision` (default 40), truncated (ROUND_DOWN), as the package's Decimal. */
export function divideOnce(x: Rational, precision: number = DIVISION_PRECISION): Decimal {
  const D =
    precision === DIVISION_PRECISION ? Div : BaseDecimal.clone({ precision, rounding: BaseDecimal.ROUND_DOWN });
  const q = new D(x.n.toString()).div(new D(x.d.toString()));
  return new Decimal(q); // the constructor never rounds; later arithmetic uses the package config
}

/**
 * `x` divided once (see divideOnce), rounded to cents with `rounding`; never negative zero.
 *
 * The division runs at precision 40, widened only when the integer part has more than 36 digits (which the
 * 1e30 money limit allows for a profit, up to 60 digits), so every cent and half-cent boundary is still a
 * representable value. Below 1e36 the result is exactly what precision 40 gives. As in Python.
 */
export function toCents(x: Rational, rounding: BaseDecimal.Rounding): Decimal {
  const integerDigits = ((x.n < 0n ? -x.n : x.n) / x.d).toString().length;
  const precision = Math.max(DIVISION_PRECISION, integerDigits + 4);
  const cents = divideOnce(x, precision).toDecimalPlaces(2, rounding);
  return cents.isZero() ? new Decimal(0) : cents;
}
