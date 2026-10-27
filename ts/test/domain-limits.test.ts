// Shared domain limits: money inputs are bounded, and decimal exponents are bounded before any digits are
// expanded. The Python suite asserts the same fixture cases (tests/test_domain_limits.py).
//
// - Money inputs (bankroll, stake, exposures, prices and every other value entering money math): |x| >= 1e30
//   is a RangeError.
// - A non-zero value entering money math or fmtProb/fmtPrice whose leading digit lies beyond 10**60 or below
//   10**-60 (decimal.js `e` outside [-60, 60]) is a RangeError at once, before any digits are expanded.
// - Zero is zero whatever its exponent.
import { describe, expect, test } from "vitest";
import {
  DEFAULT_STAKE_SETTINGS,
  Decimal,
  americanFromDecimal,
  fmtPrice,
  fmtProb,
  profit,
  settlement,
  sizeStake,
} from "../src/index.js";
import { cases } from "./cases.js";

const FAST_MS = 1000;
const MAX_MESSAGE = 200;
const WIN = settlement("1/1", "0/1");

type Case = Record<string, string | boolean>;

function run(c: Case): Decimal | string | number {
  const s = (k: string) => c[k] as string;
  switch (c.fn) {
    case "stake":
      return sizeStake({
        fairProb: new Decimal(s("fair_prob")),
        price: new Decimal(s("price")),
        bankroll: new Decimal(s("bankroll")),
        settings: {
          kellyMultiplier: new Decimal(s("kelly_multiplier")),
          betCap: new Decimal(s("bet_cap")),
          participantCap: new Decimal(s("participant_cap")),
          eventCap: new Decimal(s("event_cap")),
        },
        participantExposure: new Decimal(s("participant_exposure")),
        eventExposure: new Decimal(s("event_exposure")),
      });
    case "profit":
      return profit(new Decimal(s("stake")), new Decimal(s("price")), settlement(s("win"), s("refund")));
    case "fmt_price":
      return fmtPrice(new Decimal(s("value")));
    case "fmt_prob":
      return fmtProb(new Decimal(s("value")));
    case "american_from_decimal":
      return americanFromDecimal(new Decimal(s("value")));
    default:
      throw new Error(`unknown fn ${String(c.fn)}`);
  }
}

function thrown(fn: () => unknown): unknown {
  try {
    fn();
  } catch (e) {
    return e;
  }
  return undefined;
}

describe("domain limits fixture", () => {
  const section = cases.domain_limits as Case[];

  test("section shape", () => {
    expect(section).toHaveLength(15);
  });

  test.each(section.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const start = performance.now();
    if (c.error) {
      const e = thrown(() => run(c));
      expect(e).toBeInstanceOf(RangeError);
      expect((e as Error).message.length).toBeLessThan(MAX_MESSAGE);
    } else {
      const got = run(c) as Decimal;
      const expected = (c.fn === "stake" ? c.stake : c.profit) as string;
      expect(got.toFixed(2)).toBe(expected);
    }
    expect(performance.now() - start).toBeLessThan(FAST_MS);
  });
});

function stake(overrides: Record<string, unknown>): Decimal {
  return sizeStake({
    fairProb: new Decimal("0.25"),
    price: new Decimal("5.5"),
    bankroll: new Decimal(10000),
    settings: DEFAULT_STAKE_SETTINGS,
    participantExposure: new Decimal(0),
    eventExposure: new Decimal(0),
    ...overrides,
  } as Parameters<typeof sizeStake>[0]);
}

describe("money limits", () => {
  const names = ["bankroll", "price", "participantExposure", "eventExposure"];

  test.each(names.flatMap((n) => ["1e30", "-1e30", "1E+31", "1e60", "1e61", "1e20000000"].map((v) => [n, v])))(
    "%s = %s (|x| >= 1e30) rejected",
    (name, value) => {
      expect(() => stake({ [name]: new Decimal(value) })).toThrow(RangeError);
      expect(() => stake({ [name]: new Decimal(value) })).toThrow(name);
    },
  );

  test.each(
    ["fairProb", ...names].flatMap((n) => ["1e-61", "-1e-61", "1e-100000000", "1.5e-61"].map((v) => [n, v])),
  )("%s = %s (exponent below -60) rejected", (name, value) => {
    expect(() => stake({ [name]: new Decimal(value) })).toThrow(RangeError);
    expect(() => stake({ [name]: new Decimal(value) })).toThrow(name);
  });

  test("plain decimal strings share the limits", () => {
    expect(() => stake({ bankroll: "1" + "0".repeat(30) })).toThrow(RangeError);
    expect(stake({ bankroll: "9".repeat(30) }).toFixed(2)).toBe("19999999999999999999999999999.98");
    expect(() => stake({ bankroll: "0." + "0".repeat(60) + "1" })).toThrow(RangeError); // 1e-61
    expect(stake({ bankroll: "0." + "0".repeat(59) + "1" }).toFixed(2)).toBe("0.00"); // 1e-60
    expect(stake({ participantExposure: "0." + "0".repeat(200) }).toFixed(2)).toBe("200.00"); // zero
  });

  test("bounds are inclusive where documented", () => {
    expect(stake({ bankroll: new Decimal("1e-60") }).toFixed(2)).toBe("0.00");
    expect(stake({ bankroll: new Decimal("9.99e29") }).toFixed(2)).toBe("19980000000000000000000000000.00");
    expect(
      stake({ participantExposure: new Decimal("0E-100000000"), eventExposure: new Decimal("0E+100000000") }).toFixed(2),
    ).toBe("200.00");
  });

  test.each(["kellyMultiplier", "betCap", "participantCap", "eventCap"])("setting %s shares the exponent limit", (k) => {
    expect(() => stake({ settings: { ...DEFAULT_STAKE_SETTINGS, [k]: new Decimal("1e-61") } })).toThrow(RangeError);
    expect(() => stake({ settings: { ...DEFAULT_STAKE_SETTINGS, [k]: new Decimal("1e-60") } })).not.toThrow();
  });

  test.each(["1e30", "-1e30", "1e-61", "1e-100000000", "1e20000000"])("profit stake %s rejected", (v) => {
    expect(() => profit(new Decimal(v), new Decimal(2), WIN)).toThrow(RangeError);
    expect(() => profit(new Decimal(v), new Decimal(2), WIN)).toThrow("stake");
  });

  test.each(["1e30", "1e20000000"])("profit price %s rejected", (v) => {
    expect(() => profit(new Decimal(1), new Decimal(v), WIN)).toThrow(RangeError);
    expect(() => profit(new Decimal(1), new Decimal(v), WIN)).toThrow("price");
  });

  test("a price just above 1 with 72 fraction digits is within the limit", () => {
    expect(profit(new Decimal(1), new Decimal("1." + "0".repeat(70) + "1"), WIN).toFixed(2)).toBe("0.00");
  });

  test.each(["1e30", "1e61", "1e20000000"])("americanFromDecimal(%s) rejected", (v) => {
    expect(() => americanFromDecimal(new Decimal(v))).toThrow(RangeError);
  });
});

describe("formatting exponent limit", () => {
  test.each([
    new Decimal("1e61"),
    new Decimal("1e-61"),
    new Decimal("1e20000000"),
    new Decimal("1e-100000000"),
    1e300,
    5e-324,
  ])("fmtProb and fmtPrice reject %s fast", (value) => {
    for (const fn of [fmtProb, fmtPrice]) {
      const start = performance.now();
      expect(() => fn(value)).toThrow(RangeError);
      expect(performance.now() - start).toBeLessThan(FAST_MS);
    }
  });

  test("messages echo at most about 40 characters of the value", () => {
    const long = new Decimal("1".repeat(5000));
    for (const call of [
      () => stake({ bankroll: long }),
      () => stake({ bankroll: "1".repeat(5000) }),
      () => profit(long, new Decimal(2), WIN),
      () => fmtPrice(long),
      () => fmtPrice("1".repeat(5000)),
      () => americanFromDecimal(long),
    ]) {
      const e = thrown(call);
      expect(e).toBeInstanceOf(RangeError);
      expect((e as Error).message.length).toBeLessThan(MAX_MESSAGE);
    }
  });
});
