/** Odds basics: implied probability and American/decimal conversion. */
import type { Decimal, DecimalInput } from "./decimal.js";
import { cmp, div, divideOnce, exactMoney, mul, rat, sub, ONE } from "./_exact.js";

/** A float price for the research/display helpers: a finite number > 1. Anything else is a RangeError. */
export function checkFloatPrice(price: unknown): number {
  if (typeof price !== "number" || !(price > 1) || !Number.isFinite(price)) {
    throw new RangeError(`decimal odds must be a finite number > 1, got ${String(price)}`);
  }
  return price;
}

/** Raw implied probability (1 / decimal odds, vig included). */
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

/**
 * American odds for decimal odds: o >= 2 gives (o - 1) * 100, o < 2 gives -100 / (o - 1).
 *
 * Computed exactly and rounded half away from zero (never Math.round, which rounds -312.5 to -312).
 * o <= 1 is a RangeError, and so is a result too large to be an exact JS number.
 */
export function americanFromDecimal(o: DecimalInput): number {
  const odds = exactMoney("decimal odds", o);
  if (cmp(odds, ONE) <= 0) throw new RangeError(`decimal odds must be > 1, got ${String(o)}`);
  const profit = sub(odds, ONE);
  const exact = cmp(odds, rat(2n)) >= 0 ? mul(profit, rat(100n)) : div(rat(-100n), profit);
  const absN = exact.n < 0n ? -exact.n : exact.n;
  const magnitude = (2n * absN + exact.d) / (2n * exact.d); // floor(|x| + 1/2); both sides positive
  if (magnitude > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new RangeError(`American odds for ${String(o)} are too large to represent exactly`);
  }
  const m = Number(magnitude);
  return exact.n < 0n ? -m : m;
}
