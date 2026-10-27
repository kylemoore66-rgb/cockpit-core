import { describe, expect, test } from "vitest";
import {
  DEFAULT_STAKE_SETTINGS,
  Decimal,
  type StakeSettings,
  edge,
  fullKelly,
  sizeStake,
} from "../src/index.js";
import { cases } from "./cases.js";

type StakeArgs = Parameters<typeof sizeStake>[0];

function stakeArgs(c: Record<string, string>): StakeArgs {
  return {
    fairProb: new Decimal(c.fair_prob),
    price: new Decimal(c.price),
    bankroll: new Decimal(c.bankroll),
    settings: {
      kellyMultiplier: new Decimal(c.kelly_multiplier),
      betCap: new Decimal(c.bet_cap),
      participantCap: new Decimal(c.participant_cap),
      eventCap: new Decimal(c.event_cap),
    },
    participantExposure: new Decimal(c.participant_exposure),
    eventExposure: new Decimal(c.event_exposure),
  };
}

function validArgs(overrides: Record<string, unknown> = {}): StakeArgs {
  return {
    fairProb: new Decimal("0.25"),
    price: new Decimal("5.5"),
    bankroll: new Decimal(10000),
    settings: DEFAULT_STAKE_SETTINGS,
    participantExposure: new Decimal(0),
    eventExposure: new Decimal(0),
    ...overrides,
  } as StakeArgs;
}

describe("edge and Kelly", () => {
  test("edge and kelly match fixture", () => {
    expect(cases.edge_kelly.length).toBeGreaterThan(0);
    for (const c of cases.edge_kelly) {
      const p = Number(c.fair_prob);
      const o = Number(c.price);
      expect(Math.abs(edge(p, o) - c.edge), JSON.stringify(c)).toBeLessThanOrEqual(1e-9);
      expect(Math.abs(fullKelly(p, o) - c.full_kelly), JSON.stringify(c)).toBeLessThanOrEqual(1e-9);
    }
  });

  test("kelly is not the tennis formula", () => {
    expect(fullKelly(0.5, 2.5)).toBeCloseTo(1 / 6, 12);
    expect(Math.abs(fullKelly(0.5, 2.5) - 0.1 / 1.5)).toBeGreaterThan(1e-6);
  });

  test.each([0.0, 1.0, -0.1, 1.5, Number.NaN, true, null])("bad fair prob rejected by float helpers (%s)", (p) => {
    expect(() => edge(p as unknown as number, 2.0)).toThrow(RangeError);
    expect(() => fullKelly(p as unknown as number, 2.0)).toThrow(RangeError);
  });

  test.each([1.0, 0.5, Number.NaN, true, null, Infinity, -Infinity])("bad price rejected by float helpers (%s)", (o) => {
    expect(() => edge(0.5, o as unknown as number)).toThrow(RangeError);
    expect(() => fullKelly(0.5, o as unknown as number)).toThrow(RangeError);
  });
});

describe("stake sizing", () => {
  test("stakes match fixture", () => {
    expect(cases.stakes).toHaveLength(8);
    for (const c of cases.stakes) {
      const got = sizeStake(stakeArgs(c));
      expect(Decimal.isDecimal(got), c.name).toBe(true);
      expect(got.toFixed(2), c.name).toBe(c.stake);
      expect(got.isNegative(), c.name).toBe(false);
    }
  });

  test("stakes match fixture with string inputs too", () => {
    for (const c of cases.stakes) {
      const got = sizeStake({
        fairProb: c.fair_prob,
        price: c.price,
        bankroll: c.bankroll,
        settings: {
          kellyMultiplier: c.kelly_multiplier,
          betCap: c.bet_cap,
          participantCap: c.participant_cap,
          eventCap: c.event_cap,
        },
        participantExposure: c.participant_exposure,
        eventExposure: c.event_exposure,
      });
      expect(got.toFixed(2), c.name).toBe(c.stake);
    }
  });

  test("exact whole cent not lost", () => {
    const [c] = cases.stakes.filter((x: { name: string }) => x.name === "exact_whole_cent_not_lost");
    expect(sizeStake(stakeArgs(c)).toFixed(2)).toBe("1.00");
  });

  test("stake never negative when exposure exceeds cap", () => {
    const [c] = cases.stakes.filter((x: { name: string }) => x.name === "exposure_past_cap");
    const got = sizeStake(stakeArgs(c));
    expect(got.toFixed(2)).toBe("0.00");
    expect(got.isZero()).toBe(true);
    expect(got.isNegative()).toBe(false);
  });

  test.each<[string, Record<string, unknown>]>([
    ["fairProb 0", { fairProb: new Decimal(0) }],
    ["fairProb 1", { fairProb: new Decimal(1) }],
    ["fairProb -0.1", { fairProb: new Decimal("-0.1") }],
    ["fairProb 1.2", { fairProb: new Decimal("1.2") }],
    ["fairProb NaN", { fairProb: new Decimal(NaN) }],
    ["price 1", { price: new Decimal(1) }],
    ["price 0.5", { price: new Decimal("0.5") }],
    ["price Infinity", { price: new Decimal(Infinity) }],
    ["bankroll -0.01", { bankroll: new Decimal("-0.01") }],
    ["bankroll string -0.01", { bankroll: "-0.01" }],
    ["participantExposure -1", { participantExposure: new Decimal(-1) }],
    ["eventExposure -1", { eventExposure: new Decimal(-1) }],
    ["fairProb as number", { fairProb: 0.25 }],
    ["price as number", { price: 5.5 }],
    ["bankroll as number", { bankroll: 10000 }],
    ["bankroll undefined", { bankroll: undefined }],
    ["price exponent string", { price: "5.5e0" }],
    ["price with spaces", { price: " 5.5" }],
    ["price trailing dot", { price: "5." }],
  ])("bad inputs rejected: %s", (_label, overrides) => {
    expect(() => sizeStake(validArgs(overrides))).toThrow(RangeError);
  });

  test.each(["kellyMultiplier", "betCap", "participantCap", "eventCap"])("bad caps rejected: %s", (field) => {
    for (const value of [new Decimal("-0.01"), new Decimal("1.01"), new Decimal(NaN), 0.02, "-0.01", "1.01"]) {
      const settings = { ...DEFAULT_STAKE_SETTINGS, [field]: value } as unknown as StakeSettings;
      expect(() => sizeStake(validArgs({ settings })), `${field}=${String(value)}`).toThrow(RangeError);
    }
  });

  test("kelly multiplier above 1 rejected (no over-Kelly)", () => {
    const settings = { ...DEFAULT_STAKE_SETTINGS, kellyMultiplier: new Decimal("1.5") };
    expect(() => sizeStake(validArgs({ settings }))).toThrow(RangeError);
  });

  test("cap bounds inclusive", () => {
    const zero = { ...DEFAULT_STAKE_SETTINGS, betCap: new Decimal(0) };
    const gotZero = sizeStake(validArgs({ settings: zero }));
    expect(gotZero.toFixed(2)).toBe("0.00");
    expect(gotZero.isNegative()).toBe(false);
    const one: StakeSettings = {
      kellyMultiplier: new Decimal(1),
      betCap: new Decimal(1),
      participantCap: new Decimal(1),
      eventCap: new Decimal(1),
    };
    // full Kelly 1/12 of 10000 = 833.333... -> 833.33
    expect(sizeStake(validArgs({ settings: one })).toFixed(2)).toBe("833.33");
  });

  test("value just under a cent never rounds up", () => {
    const settings = { ...DEFAULT_STAKE_SETTINGS, kellyMultiplier: new Decimal(1), betCap: new Decimal("0.01") };
    const got = sizeStake(validArgs({ bankroll: new Decimal("0." + "9".repeat(45)), settings }));
    expect(got.toFixed(2)).toBe("0.00");
    expect(got.isNegative()).toBe(false);
  });

  test("default settings", () => {
    const s = DEFAULT_STAKE_SETTINGS;
    expect([s.kellyMultiplier, s.betCap, s.participantCap, s.eventCap].map((d) => new Decimal(d).toString())).toEqual([
      "0.25",
      "0.02",
      "0.05",
      "0.05",
    ]);
    expect(Object.isFrozen(s)).toBe(true);
  });

  test("wrong structure is a TypeError", () => {
    expect(() => sizeStake(undefined as unknown as StakeArgs)).toThrow(TypeError);
    expect(() => sizeStake(validArgs({ settings: null }))).toThrow(TypeError);
    expect(() => sizeStake(validArgs({ settings: "default" }))).toThrow(TypeError);
    expect(() => sizeStake(validArgs({ settings: { kellyMultiplier: new Decimal(1) } }))).toThrow(TypeError);
    const { bankroll: _omit, ...missing } = validArgs();
    expect(() => sizeStake(missing as unknown as StakeArgs)).toThrow(TypeError);
  });
});
