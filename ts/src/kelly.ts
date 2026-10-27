/**
 * Edge, Kelly fraction and capped stake sizing.
 *
 * `edge` and `fullKelly` are float helpers for research and display. `sizeStake` is money: it takes
 * Decimals (or decimal strings), computes exactly with bigint rationals, divides once at the end and
 * rounds the stake DOWN to cents.
 */
import { Decimal as BaseDecimal } from "decimal.js";
import { Decimal, type DecimalInput } from "./decimal.js";
import { checkFloatPrice } from "./odds.js";
import { ONE, ZERO, type Rational, cmp, div, exactMoney, max, min, mul, sub, toCents } from "./_exact.js";

function checkFloatProb(fairProb: unknown): number {
  if (typeof fairProb !== "number" || !(fairProb > 0 && fairProb < 1)) {
    throw new RangeError(`fairProb must be strictly between 0 and 1, got ${String(fairProb)}`);
  }
  return fairProb;
}

/** Expected profit per unit staked: p * o - 1. The price must be finite and > 1. */
export function edge(fairProb: number, price: number): number {
  const p = checkFloatProb(fairProb);
  const o = checkFloatPrice(price);
  return p * o - 1;
}

/** Full-Kelly fraction of bankroll: max(0, (p * o - 1) / (o - 1)). */
export function fullKelly(fairProb: number, price: number): number {
  const e = edge(fairProb, price);
  return Math.max(0, e / (price - 1));
}

/**
 * Fractional-Kelly multiplier and caps, each a fraction of bankroll in [0, 1].
 *
 * `eventCap` covers every market of one event together, so mutually exclusive outrights share it.
 */
export type StakeSettings = {
  readonly kellyMultiplier: DecimalInput;
  readonly betCap: DecimalInput;
  readonly participantCap: DecimalInput;
  readonly eventCap: DecimalInput;
};

export const DEFAULT_STAKE_SETTINGS: StakeSettings = Object.freeze({
  kellyMultiplier: new Decimal("0.25"),
  betCap: new Decimal("0.02"),
  participantCap: new Decimal("0.05"),
  eventCap: new Decimal("0.05"),
});

const SETTING_KEYS = ["kellyMultiplier", "betCap", "participantCap", "eventCap"] as const;
const ARG_KEYS = ["fairProb", "price", "bankroll", "settings", "participantExposure", "eventExposure"] as const;

function isObject(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x) && !BaseDecimal.isDecimal(x);
}

function checkSettings(settings: unknown): Record<(typeof SETTING_KEYS)[number], Rational> {
  if (!isObject(settings) || !SETTING_KEYS.every((k) => k in settings)) {
    throw new TypeError(`settings must be a StakeSettings with ${SETTING_KEYS.join(", ")}`);
  }
  const out = {} as Record<(typeof SETTING_KEYS)[number], Rational>;
  for (const k of SETTING_KEYS) {
    const v = exactMoney(k, settings[k]);
    if (cmp(v, ZERO) < 0 || cmp(v, ONE) > 0) throw new RangeError(`${k} must be in [0, 1], got ${String(settings[k])}`);
    out[k] = v;
  }
  return out;
}

/**
 * Fractional-Kelly stake, capped per bet, per participant and per event, rounded DOWN to cents.
 *
 * stake = max(0, min(B*m*(p*o - 1)/(o - 1), B*betCap, B*participantCap - participantExposure,
 *                    B*eventCap - eventExposure))
 *
 * Computed exactly as one rational and divided once, so no cent is lost to early rounding. Exposure
 * already past a cap gives 0.00, never a negative stake.
 */
export function sizeStake(args: {
  fairProb: DecimalInput;
  price: DecimalInput;
  bankroll: DecimalInput;
  settings: StakeSettings;
  participantExposure: DecimalInput;
  eventExposure: DecimalInput;
}): Decimal {
  if (!isObject(args) || !ARG_KEYS.every((k) => k in args)) {
    throw new TypeError(`sizeStake needs an object with ${ARG_KEYS.join(", ")}`);
  }
  const s = checkSettings(args.settings);
  const p = exactMoney("fairProb", args.fairProb);
  const o = exactMoney("price", args.price);
  const b = exactMoney("bankroll", args.bankroll);
  const participantUsed = exactMoney("participantExposure", args.participantExposure);
  const eventUsed = exactMoney("eventExposure", args.eventExposure);
  if (!(cmp(p, ZERO) > 0 && cmp(p, ONE) < 0)) {
    throw new RangeError(`fairProb must be strictly between 0 and 1, got ${String(args.fairProb)}`);
  }
  if (cmp(o, ONE) <= 0) throw new RangeError(`price must be > 1, got ${String(args.price)}`);
  if (cmp(b, ZERO) < 0) throw new RangeError(`bankroll must be >= 0, got ${String(args.bankroll)}`);
  if (cmp(participantUsed, ZERO) < 0 || cmp(eventUsed, ZERO) < 0) throw new RangeError("exposures must be >= 0");

  const raw = div(mul(mul(b, s.kellyMultiplier), sub(mul(p, o), ONE)), sub(o, ONE));
  const exact = max(
    ZERO,
    min(
      raw,
      mul(b, s.betCap),
      sub(mul(b, s.participantCap), participantUsed),
      sub(mul(b, s.eventCap), eventUsed),
    ),
  );
  // The single division: truncated to 40 digits, so a value just under a cent is never lifted onto it
  // before the final round-down to cents.
  return toCents(exact, BaseDecimal.ROUND_DOWN);
}
