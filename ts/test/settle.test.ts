import { describe, expect, test } from "vitest";
import { Decimal, type Settlement, profit, settlement } from "../src/index.js";
import { cases } from "./cases.js";

const WIN = settlement("1/1", "0/1");
const LOSS = settlement("0/1", "0/1");

describe("settlement", () => {
  test("settlement matches fixture", () => {
    expect(cases.settlement).toHaveLength(11);
    for (const c of cases.settlement) {
      const got = profit(new Decimal(c.stake), new Decimal(c.price), settlement(c.win, c.refund));
      expect(Decimal.isDecimal(got), c.name).toBe(true);
      expect(got.toFixed(2), c.name).toBe(c.profit);
      if (got.isZero()) expect(got.isNegative(), c.name).toBe(false);
    }
  });

  test("settlement matches fixture with string money", () => {
    for (const c of cases.settlement) {
      expect(profit(c.stake, c.price, settlement(c.win, c.refund)).toFixed(2), c.name).toBe(c.profit);
    }
  });

  test("settlement parses n/d into bigints", () => {
    const s = settlement("2/3", "0/1");
    expect(s.win).toEqual([2n, 3n]);
    expect(s.refund).toEqual([0n, 1n]);
    expect(Object.isFrozen(s)).toBe(true);
    expect(settlement("1/3", "2/3").refund).toEqual([2n, 3n]);
  });

  test.each<[string, string]>([
    ["1/0", "0/1"],
    ["0/1", "1/0"],
    ["-1/2", "0/1"],
    ["0/1", "-1/2"],
    ["1/-2", "0/1"],
    ["1/2", "2/3"],
    ["3/2", "0/1"],
    ["0.5", "0/1"],
    ["1", "0/1"],
    ["", "0/1"],
    [" 1/2", "0/1"],
    ["1/2/3", "0/1"],
    ["NaN/1", "0/1"],
  ])("bad settlement values rejected (%s, %s)", (w, r) => {
    expect(() => settlement(w, r)).toThrow(RangeError);
  });

  test.each([null, undefined, 0.5, 1, true, [1n, 2n]])("non-string settlement is a TypeError (%s)", (bad) => {
    expect(() => settlement(bad as unknown as string, "0/1")).toThrow(TypeError);
    expect(() => settlement("0/1", bad as unknown as string)).toThrow(TypeError);
  });

  test("profit dead heat does not round the fraction first", () => {
    // 1/6 as 0.1667 first would give -6.874... -> -6.87. Exact is -6.875 -> -6.88.
    expect(profit(new Decimal(11), new Decimal("2.25"), settlement("1/6", "0/1")).toFixed(2)).toBe("-6.88");
  });

  test("profit just below half cent rounds down on both sides", () => {
    const price = "1." + "0".repeat(2) + "4" + "9".repeat(60);
    expect(profit(new Decimal(1), new Decimal(price), WIN).toFixed(2)).toBe("0.00");
    expect(profit(new Decimal(1), new Decimal("1.005"), WIN).toFixed(2)).toBe("0.01");
    const lossZero = profit(new Decimal("0.00" + "4" + "9".repeat(60)), new Decimal(2), LOSS);
    expect(lossZero.toFixed(2)).toBe("0.00");
    expect(lossZero.isNegative()).toBe(false);
    expect(profit(new Decimal("0.005"), new Decimal(2), LOSS).toFixed(2)).toBe("-0.01");
  });

  test("negative zero normalised fixture", () => {
    const [c] = cases.settlement.filter((x: { name: string }) => x.name === "negative_zero_normalised");
    const got = profit(new Decimal(c.stake), new Decimal(c.price), settlement(c.win, c.refund));
    expect(got.toFixed(2)).toBe("0.00");
    expect(got.isNegative()).toBe(false);
  });

  test("profit never returns negative zero", () => {
    const got = profit(new Decimal("0.004"), new Decimal(2), LOSS); // exact -0.004
    expect(got.toFixed(2)).toBe("0.00");
    expect(got.isZero()).toBe(true);
    expect(got.isNegative()).toBe(false);
  });

  test.each<[unknown, unknown]>([
    [100.0, new Decimal(2)],
    [new Decimal(100), 2.0],
    [100, new Decimal(2)],
    [new Decimal(NaN), new Decimal(2)],
    [new Decimal(Infinity), new Decimal(2)],
    [new Decimal(-1), new Decimal(2)],
    ["-1", "2"],
    [new Decimal(100), new Decimal(1)],
    [new Decimal(100), new Decimal("0.5")],
    [new Decimal(100), new Decimal(NaN)],
    [null, new Decimal(2)],
    [true, new Decimal(2)],
    ["1e2", "2"],
    ["100", "2."],
  ])("profit rejects bad money inputs (%s, %s)", (stake, price) => {
    expect(() => profit(stake as Decimal, price as Decimal, WIN)).toThrow(RangeError);
  });

  test("profit needs a settlement", () => {
    for (const bad of [null, undefined, [1, 0], { win: 1, refund: 0 }, { win: [1n, 1n] }, "win"]) {
      expect(() => profit(new Decimal(1), new Decimal(2), bad as unknown as Settlement)).toThrow(TypeError);
    }
  });

  test("profit re-checks a hand-built settlement's values", () => {
    const bad: Settlement[] = [
      { win: [1n, 0n], refund: [0n, 1n] },
      { win: [-1n, 2n], refund: [0n, 1n] },
      { win: [1n, 2n], refund: [2n, 3n] },
    ];
    for (const s of bad) expect(() => profit(new Decimal(1), new Decimal(2), s)).toThrow(RangeError);
  });
});
