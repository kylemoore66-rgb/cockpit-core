import { describe, expect, test } from "vitest";
import { Decimal, americanFromDecimal, decimalFromAmerican, implied } from "../src/index.js";
import { cases } from "./cases.js";

describe("odds conversion", () => {
  test("conversions match fixture", () => {
    expect(cases.odds_conversion).toHaveLength(11);
    let checked = 0;
    for (const c of cases.odds_conversion) {
      if ("decimal_4dp" in c) {
        const got = decimalFromAmerican(c.american).toDecimalPlaces(4, Decimal.ROUND_HALF_UP).toFixed(4);
        expect(got, JSON.stringify(c)).toBe(c.decimal_4dp);
        checked += 1;
      }
      if ("decimal" in c) {
        expect(americanFromDecimal(c.decimal), JSON.stringify(c)).toBe(c.american);
        expect(americanFromDecimal(new Decimal(c.decimal)), JSON.stringify(c)).toBe(c.american);
        checked += 1;
      }
    }
    expect(checked).toBe(cases.odds_conversion.length);
  });

  test("decimalFromAmerican matches Python to all 40 digits", () => {
    // From `str(decimal_from_american(a))` in the Python package: one division, precision 40, truncated.
    expect(decimalFromAmerican(-150).toString()).toBe("1.666666666666666666666666666666666666666");
    expect(decimalFromAmerican(-110).toString()).toBe("1.909090909090909090909090909090909090909");
    expect(decimalFromAmerican(450).toString()).toBe("5.5");
    expect(decimalFromAmerican(100).toString()).toBe("2");
    expect(decimalFromAmerican(-100).toString()).toBe("2");
  });

  test("americanFromDecimal rounds half away from zero at the 2.0 boundary", () => {
    expect(americanFromDecimal("2.0")).toBe(100);
    expect(americanFromDecimal("1.99")).toBe(-101);
    expect(americanFromDecimal("1.32")).toBe(-313);
    expect(americanFromDecimal("2.245")).toBe(125);
  });

  test.each([1.0, 0.5, Number.NaN, true, null, undefined, Infinity, -Infinity, "2.0"])(
    "bad prices rejected by implied (%s)",
    (bad) => {
      expect(() => implied(bad as unknown as number)).toThrow(RangeError);
    },
  );

  test("implied is 1 / price", () => {
    expect(implied(2)).toBe(0.5);
    expect(implied(4)).toBe(0.25);
  });

  test.each([0, 50, -99, 99, 100.5, -150.5, Number.NaN, Infinity, true, null, "150"])(
    "bad american rejected (%s)",
    (bad) => {
      expect(() => decimalFromAmerican(bad as unknown as number)).toThrow(RangeError);
    },
  );

  test.each([new Decimal(1), new Decimal("0.5"), new Decimal(0), new Decimal(NaN), new Decimal(Infinity), "1", "0.5", "-2", "2e0", " 2", "", 2, null])(
    "bad decimal rejected for american (%s)",
    (bad) => {
      expect(() => americanFromDecimal(bad as unknown as Decimal)).toThrow(RangeError);
    },
  );
});
