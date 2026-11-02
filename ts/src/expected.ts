/**
 * Expected profit, profit variance and the cumulative band: what a bettor should have made, and how far
 * from it luck alone can take him. The TS twin of the Python package's `expected` module.
 *
 * For a stake b at decimal price o with fair win probability p, profit is b(o - 1) with probability p and
 * -b otherwise, so the expected profit is b(p*o - 1) and the variance b^2 * o^2 * p(1 - p). `outcomeMoments`
 * generalises this to any list of settled outcomes (pushes, half wins, dead heats), each with its
 * probability. `cumulativeBand` runs a sequence of bets into the band a Results screen draws: the running
 * total of expected profit, and the standard deviation of the running total (independent bets, so
 * variances add).
 *
 * Money math, like `profit`: inputs are computed exactly with bigint rationals and each result is divided
 * once, at precision 40 truncated (ROUND_DOWN), exactly as in Python, so both packages return the same
 * value. Results are NOT rounded to cents: round for display only (`toFixed(2)`), and compare by value
 * (`eq`). Inputs are decimal.js Decimals or plain decimal strings, inside the shared money domain.
 */
import { Decimal as BaseDecimal } from "decimal.js";
import { Decimal, type DecimalInput } from "./decimal.js";
import { ONE, ZERO, type Rational, add, cmp, divideOnce, exactMoney, mul, show, sub } from "./_exact.js";
import { type Settlement, settlementFractions } from "./settle.js";

function stakeOf(stake: unknown): Rational {
  const b = exactMoney("stake", stake);
  if (cmp(b, ZERO) < 0) throw new RangeError(`stake must be >= 0, got ${show(stake)}`);
  return b;
}

function priceOf(price: unknown): Rational {
  const o = exactMoney("price", price);
  if (cmp(o, ONE) <= 0) throw new RangeError(`price must be > 1, got ${show(price)}`);
  return o;
}

function probabilityOf(name: string, value: unknown): Rational {
  const p = exactMoney(name, value);
  if (cmp(p, ZERO) < 0 || cmp(p, ONE) > 0) throw new RangeError(`${name} must be between 0 and 1, got ${show(value)}`);
  return p;
}

/**
 * Expected profit of a win/lose bet: stake * (p * o - 1), exact, divided once (precision 40), not rounded.
 *
 * Needs stake >= 0, 0 <= fairProb <= 1 and price > 1. Stake 100 at 1.9091 with p = 0.55 is exactly 5.0005.
 */
export function expectedProfit(stake: DecimalInput, fairProb: DecimalInput, price: DecimalInput): Decimal {
  const b = stakeOf(stake);
  const p = probabilityOf("fairProb", fairProb);
  const o = priceOf(price);
  return divideOnce(mul(b, sub(mul(p, o), ONE)));
}

/**
 * Variance of a win/lose bet's profit: stake^2 * o^2 * p(1 - p), exact, divided once (precision 40).
 *
 * The same inputs and checks as `expectedProfit`. Equal to `outcomeMoments` over WIN with p and LOSS
 * with 1 - p.
 */
export function profitVariance(stake: DecimalInput, fairProb: DecimalInput, price: DecimalInput): Decimal {
  const b = stakeOf(stake);
  const p = probabilityOf("fairProb", fairProb);
  const o = priceOf(price);
  return divideOnce(mul(mul(mul(b, b), mul(o, o)), mul(p, sub(ONE, p))));
}

/**
 * [mean, variance] of a bet's profit over settled outcomes, each a [probability, Settlement] pair.
 *
 * An outcome settled s pays stake * (s.win * o + s.refund - 1), as `profit` does before rounding. The
 * probabilities must each be in [0, 1] and sum to exactly 1 (an exact check, no tolerance), so an empty
 * array is a RangeError. Both moments are exact and divided once (precision 40), not rounded. `outcomes`
 * that is not an array of pairs, or a settlement that is not a Settlement, is a TypeError; every bad value
 * is a RangeError.
 */
export function outcomeMoments(
  stake: DecimalInput,
  price: DecimalInput,
  outcomes: Array<[DecimalInput, Settlement]>,
): [Decimal, Decimal] {
  const b = stakeOf(stake);
  const o = priceOf(price);
  if (!Array.isArray(outcomes)) {
    throw new TypeError(`outcomes must be an array of [probability, Settlement] pairs, got ${show(outcomes)}`);
  }
  const weighted = outcomes.map((item: unknown): [Rational, Rational] => {
    if (!Array.isArray(item) || item.length !== 2) {
      throw new TypeError(`outcomes must be [probability, Settlement] pairs, got ${show(item)}`);
    }
    const [w, r] = settlementFractions("each outcome's settlement", item[1]);
    const q = probabilityOf("outcome probability", item[0]);
    return [q, mul(b, sub(add(mul(w, o), r), ONE))];
  });
  const total = weighted.reduce((sum, [q]) => add(sum, q), ZERO);
  if (cmp(total, ONE) !== 0) {
    throw new RangeError(`outcome probabilities must sum to exactly 1, got ${total.n}/${total.d}`);
  }
  const mean = weighted.reduce((sum, [q, x]) => add(sum, mul(q, x)), ZERO);
  const variance = weighted.reduce((sum, [q, x]) => {
    const deviation = sub(x, mean);
    return add(sum, mul(q, mul(deviation, deviation)));
  }, ZERO);
  return [divideOnce(mean), divideOnce(variance)];
}

/** One point of the cumulative band: the running total of expected profit, and its standard deviation. */
export type BandPoint = { readonly expected: Decimal; readonly sigma: number };

// Addition at decimal.js's maximum precision is exact, and it only ever produces as many digits as the
// inputs span, so the maximum precision costs nothing.
const Exact = BaseDecimal.clone({ precision: 1e9, rounding: BaseDecimal.ROUND_HALF_EVEN });

function bandValue(name: string, value: unknown): BaseDecimal {
  if (!BaseDecimal.isDecimal(value)) throw new RangeError(`${name} must be a Decimal, got ${show(value)}`);
  exactMoney(name, value); // finite and inside the money domain
  return new Exact(value as BaseDecimal); // the constructor never rounds
}

/**
 * The band after each bet: running sum of expected profit, and sqrt of the running sum of variance.
 *
 * `bets` holds [expected, variance] Decimal pairs, for example from `expectedProfit` and `profitVariance`
 * (or `outcomeMoments`), one per bet in order; the bets are taken as independent, so variances add. Each
 * value must be a finite decimal.js Decimal inside the money domain (strings are not accepted: an expected
 * profit is often negative), and a variance must be >= 0: a RangeError otherwise. `bets` that is not an
 * array of pairs is a TypeError.
 *
 * The running sum of expected profit is exact (no precision limit), as in Python. `sigma` is
 * `Math.sqrt(Number(running variance))`: a number for drawing, correctly rounded at each step, so it is the
 * same double as Python's `math.sqrt(float(...))`. A zero is never negative zero.
 */
export function cumulativeBand(bets: Array<[Decimal, Decimal]>): BandPoint[] {
  if (!Array.isArray(bets)) {
    throw new TypeError(`bets must be an array of [expected, variance] Decimal pairs, got ${show(bets)}`);
  }
  const checked = bets.map((item: unknown): [BaseDecimal, BaseDecimal] => {
    if (!Array.isArray(item) || item.length !== 2) {
      throw new TypeError(`bets must be [expected, variance] Decimal pairs, got ${show(item)}`);
    }
    const expected = bandValue("expected", item[0]);
    const variance = bandValue("variance", item[1]);
    if (variance.isNegative() && !variance.isZero()) {
      throw new RangeError(`variance must be >= 0, got ${show(item[1])}`);
    }
    return [expected, variance];
  });
  let totalExpected = new Exact(0);
  let totalVariance = new Exact(0);
  return checked.map(([expected, variance]): BandPoint => {
    totalExpected = totalExpected.plus(expected);
    totalVariance = totalVariance.plus(variance);
    const pointExpected = totalExpected.isZero() ? new Decimal(0) : new Decimal(totalExpected); // no "-0"
    const pointVariance = totalVariance.isZero() ? 0 : Number(totalVariance);
    return Object.freeze({ expected: pointExpected, sigma: Math.sqrt(pointVariance) });
  });
}
