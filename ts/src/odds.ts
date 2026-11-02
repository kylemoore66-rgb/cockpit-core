/** Odds basics: implied probability and American/decimal conversion. */
import { Decimal, type DecimalInput } from "./decimal.js";
import { cmp, div, divideOnce, exactMoney, mul, rat, show, sub, ONE } from "./_exact.js";

/** A float price for the research/display helpers: a finite number > 1. Anything else is a RangeError. */
export function checkFloatPrice(price: unknown): number {
  if (typeof price !== "number" || !(price > 1) || !Number.isFinite(price)) {
    throw new RangeError(`decimal odds must be a finite number > 1, got ${String(price)}`);
  }
  return price;
}

/**
 * Raw implied probability (1 / decimal odds, vig included).
 *
 * `implied(Infinity)` is a RangeError here, while the Python package's `implied(float("inf"))` returns 0.0
 * (kept there for parity with the golf code it was ported from). A documented difference.
 */
export function implied(price: number): number {
  return 1 / checkFloatPrice(price);
}

/**
 * Decimal odds for American odds: +a gives 1 + a/100, -a gives 1 + 100/a.
 *
 * Computed exactly and divided once, at precision 40 truncated (ROUND_DOWN), so the full string matches
 * the Python package digit for digit. `a` must be a safe integer with |a| >= 100.
 */
export function decimalFromAmerican(a: number): Decimal {
  if (typeof a !== "number" || !Number.isSafeInteger(a) || Math.abs(a) < 100) {
    throw new RangeError(`American odds must be an integer with |a| >= 100, got ${String(a)}`);
  }
  const n = BigInt(a);
  return divideOnce(n > 0n ? rat(100n + n, 100n) : rat(-n + 100n, -n));
}

const PRICE_PLACES = 8;
const PRICE_SCALE = 10n ** BigInt(PRICE_PLACES);

/**
 * The stored decimal price of a bet placed at American odds `a`: the bet-price storage rule.
 *
 * +a gives 1 + a/100 and -a gives 1 + 100/a, computed as an exact rational and rounded half-up to exactly
 * 8 decimal places (so -51200, exactly 1.001953125, stores as 1.00195313), the same value as the Python
 * package's `price_decimal_from_american`. The rounding is done in bigints, so it is exact. Serialise the
 * result with `toFixed(8)` (decimal.js drops trailing zeros elsewhere): `priceDecimalFromAmerican(150)
 * .toFixed(8) === "2.50000000"`.
 *
 * This is the rule the database applies to a stored bet price, and it differs from `decimalFromAmerican`
 * (precision 40, truncated), which is unchanged. RangeError for anything that is not a safe integer,
 * |a| < 100, and -100 (the database refuses it; callers normalise -100 to +100).
 */
export function priceDecimalFromAmerican(a: number): Decimal {
  if (typeof a !== "number" || !Number.isSafeInteger(a) || Math.abs(a) < 100 || a === -100) {
    throw new RangeError(`American odds must be an integer with |a| >= 100 and not -100, got ${show(a)}`);
  }
  const n = BigInt(a);
  const exact = n > 0n ? rat(100n + n, 100n) : rat(-n + 100n, -n);
  const units = (2n * exact.n * PRICE_SCALE + exact.d) / (2n * exact.d); // floor(x * 1e8 + 1/2); x > 0
  const frac = (units % PRICE_SCALE).toString().padStart(PRICE_PLACES, "0");
  return new Decimal(`${units / PRICE_SCALE}.${frac}`); // the constructor never rounds
}

/**
 * American odds for decimal odds: o >= 2 gives (o - 1) * 100, o < 2 gives -100 / (o - 1).
 *
 * Computed exactly and rounded half away from zero (never Math.round, which rounds -312.5 to -312).
 * o <= 1 is a RangeError, and so are o >= 1e30 (the shared money limit) and a result too large to be an
 * exact JS number.
 */
export function americanFromDecimal(o: DecimalInput): number {
  const odds = exactMoney("decimal odds", o);
  if (cmp(odds, ONE) <= 0) throw new RangeError(`decimal odds must be > 1, got ${show(o)}`);
  const profit = sub(odds, ONE);
  const exact = cmp(odds, rat(2n)) >= 0 ? mul(profit, rat(100n)) : div(rat(-100n), profit);
  const absN = exact.n < 0n ? -exact.n : exact.n;
  const magnitude = (2n * absN + exact.d) / (2n * exact.d); // floor(|x| + 1/2); both sides positive
  if (magnitude > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new RangeError(`American odds for ${show(o)} are too large to represent exactly`);
  }
  const m = Number(magnitude);
  return exact.n < 0n ? -m : m;
}
