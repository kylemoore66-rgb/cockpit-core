/**
 * Settlement: a bet's (win, refund) fractions and its profit.
 *
 * A settled bet pays back `win` of the stake at the price and `refund` of the stake at evens, and loses
 * the rest, so profit per unit staked is w * o + r - 1. A full win is 1/1 and 0/1, a loss 0/1 and 0/1,
 * a void 0/1 and 1/1, a half win 1/2 and 1/2, a dead heat for k places among t tied players k/t and 0/1.
 *
 * `profit` is money: Decimal in and out, computed exactly with bigint rationals, divided once, and
 * rounded half-up (away from zero) to cents.
 */
import { Decimal as BaseDecimal } from "decimal.js";
import type { Decimal, DecimalInput } from "./decimal.js";
import { ONE, type Rational, add, cmp, exactMoney, mul, show, sub, toCents } from "./_exact.js";

/** Exact fractions [numerator, denominator] of the stake paid at the price and refunded at evens. */
export type Settlement = { readonly win: readonly [bigint, bigint]; readonly refund: readonly [bigint, bigint] };

const FRACTION = /^([0-9]+)\/([0-9]+)$/;

function parseFraction(name: string, text: unknown): [bigint, bigint] {
  if (typeof text !== "string") throw new TypeError(`${name} must be an "n/d" string, got ${String(text)}`);
  const m = FRACTION.exec(text);
  if (m === null) throw new RangeError(`${name} must be "n/d" with non-negative integers, got ${JSON.stringify(text)}`);
  return [BigInt(m[1]), BigInt(m[2])];
}

function isPair(x: unknown): x is readonly [bigint, bigint] {
  return Array.isArray(x) && x.length === 2 && typeof x[0] === "bigint" && typeof x[1] === "bigint";
}

/** Checks 0 <= win, 0 <= refund, win + refund <= 1 and non-zero denominators; returns them as rationals. */
function checkValues(win: readonly [bigint, bigint], refund: readonly [bigint, bigint]): [Rational, Rational] {
  const [wn, wd] = win;
  const [rn, rd] = refund;
  if (wd <= 0n || rd <= 0n) throw new RangeError("settlement denominators must be > 0");
  if (wn < 0n || rn < 0n) throw new RangeError("settlement fractions must be >= 0");
  const w = { n: wn, d: wd };
  const r = { n: rn, d: rd };
  if (cmp(add(w, r), ONE) > 0) {
    throw new RangeError(`need win + refund <= 1; got win=${wn}/${wd}, refund=${rn}/${rd}`);
  }
  return [w, r];
}

/** A settlement from "n/d" strings, e.g. settlement("2/3", "0/1") for a dead heat paying 2 of 3. */
export function settlement(win: string, refund: string): Settlement {
  const w = parseFraction("win", win);
  const r = parseFraction("refund", refund);
  checkValues(w, r);
  return Object.freeze({ win: Object.freeze(w), refund: Object.freeze(r) });
}

/**
 * Profit in money: stake * (w * o + r - 1), exact, rounded half-up (away from zero) to cents.
 *
 * The win fraction is never turned into a decimal before multiplying: stake 11 at 2.25 with win 1/6 is
 * exactly -6.875 and settles at -6.88. Never returns negative zero.
 */
export function profit(stake: DecimalInput, price: DecimalInput, s: Settlement): Decimal {
  if (typeof s !== "object" || s === null || !isPair(s.win) || !isPair(s.refund)) {
    throw new TypeError("s must be a Settlement ({ win: [n, d], refund: [n, d] } of bigints)");
  }
  const [w, r] = checkValues(s.win, s.refund);
  const b = exactMoney("stake", stake);
  const o = exactMoney("price", price);
  if (b.n < 0n) throw new RangeError(`stake must be >= 0, got ${show(stake)}`);
  if (cmp(o, ONE) <= 0) throw new RangeError(`price must be > 1, got ${show(price)}`);

  const exact = mul(b, sub(add(mul(w, o), r), ONE));
  // The single division (precision 40, truncated) never moves a value across a half-cent boundary, so
  // the final half-up rounding sees the same side of every boundary as the exact value does.
  return toCents(exact, BaseDecimal.ROUND_HALF_UP);
}
