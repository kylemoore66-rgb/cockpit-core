// Shared precision-edge fixtures: values a hair under a rounding boundary must not be lifted onto it.
// The Python suite asserts the same cases (tests/test_precision_edge.py).
import { expect, test } from "vitest";
import { Decimal, profit, settlement, sizeStake } from "../src/index.js";
import { cases } from "./cases.js";

function stake(c: Record<string, string>): Decimal {
  return sizeStake({
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
  });
}

test("precision edge matches fixture", () => {
  const section = cases.precision_edge as Record<string, string>[];
  expect(section).toHaveLength(3);
  expect(section.map((c) => c.kind).sort()).toEqual(["profit", "profit", "stake"]);
  for (const c of section) {
    let got: Decimal;
    let expected: string;
    if (c.kind === "stake") {
      got = stake(c);
      expected = c.stake;
    } else {
      got = profit(new Decimal(c.stake), new Decimal(c.price), settlement(c.win, c.refund));
      expected = c.profit;
    }
    expect(got.toFixed(2), c.name).toBe(expected);
    expect(got.isNegative(), c.name).toBe(false);
  }
});
