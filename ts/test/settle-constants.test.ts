// The named settlements (WIN, LOSS, VOID, HALF_WIN, HALF_LOSS), checked against the shared
// `settlement_constants` fixture that the Python suite also checks its constants against.
import { describe, expect, test } from "vitest";
import { HALF_LOSS, HALF_WIN, LOSS, type Settlement, VOID, WIN, profit, settlement } from "../src/index.js";
import { cases } from "./cases.js";

const NAMED: Record<string, Settlement> = { WIN, LOSS, VOID, HALF_WIN, HALF_LOSS };
const fixture = cases.settlement_constants as Record<string, { win: string; refund: string }>;

describe("settlement constants", () => {
  test("the fixture names exactly the five constants", () => {
    expect(Object.keys(fixture).sort()).toEqual(Object.keys(NAMED).sort());
  });

  test.each(Object.keys(NAMED))("%s equals settlement() of its fixture fractions", (name) => {
    const want = fixture[name];
    expect(NAMED[name], name).toEqual(settlement(want.win, want.refund));
  });

  test.each(Object.keys(NAMED))("%s is frozen, tuples included", (name) => {
    const s = NAMED[name];
    expect(Object.isFrozen(s), name).toBe(true);
    expect(Object.isFrozen(s.win), name).toBe(true);
    expect(Object.isFrozen(s.refund), name).toBe(true);
    // ES modules run in strict mode, so writes to a frozen object throw.
    expect(() => {
      (s as { win: unknown }).win = [0n, 1n];
    }).toThrow(TypeError);
    expect(() => {
      (s.win as unknown as bigint[])[0] = 7n;
    }).toThrow(TypeError);
    expect(() => {
      (s.refund as unknown as bigint[]).push(1n);
    }).toThrow(TypeError);
    expect(NAMED[name]).toEqual(settlement(fixture[name].win, fixture[name].refund));
  });

  test("the constants settle the shared settlement cases like settlement() does", () => {
    const byName: Record<string, Settlement> = {
      win: WIN,
      loss: LOSS,
      void: VOID,
      half_win: HALF_WIN,
      half_loss: HALF_LOSS,
    };
    let seen = 0;
    for (const c of cases.settlement) {
      const s = byName[c.name];
      if (s === undefined) continue;
      expect(profit(c.stake, c.price, s).toFixed(2), c.name).toBe(c.profit);
      seen += 1;
    }
    expect(seen).toBe(5);
  });
});
