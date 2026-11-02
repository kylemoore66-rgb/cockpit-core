// Expected profit, profit variance, outcome moments and the cumulative band (shared `expected` fixture).
// Results are unrounded (one division at precision 40, truncated), so fixture values are compared by
// value (decimal.js `eq`), not as strings. The Python suite checks the same fixture.
import { describe, expect, test } from "vitest";
import {
  Decimal,
  HALF_LOSS,
  HALF_WIN,
  LOSS,
  type Settlement,
  VOID,
  WIN,
  cumulativeBand,
  expectedProfit,
  outcomeMoments,
  profitVariance,
  settlement,
} from "../src/index.js";
import { cases } from "./cases.js";

type Frac = { win: string; refund: string };
type Binary = { name: string; stake: string; p: string; o: string; expected_profit: string; variance: string };
type Outcomes = { name: string; stake: string; price: string; outcomes: [string, Frac][]; mean: string; variance: string };
type Band = { name: string; bets: [string, string][]; points: { expected: string; sigma: number }[] };
const fixture = cases.expected as { binary: Binary[]; outcomes: Outcomes[]; band: Band[] };

const toOutcomes = (rows: [string, Frac][]): Array<[string, Settlement]> =>
  rows.map(([q, s]) => [q, settlement(s.win, s.refund)]);

// A small seeded generator (mulberry32), so the property cases are the same on every run.
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const randInt = (r: () => number, lo: number, hi: number) => lo + Math.floor(r() * (hi - lo + 1));

describe("expected: shared fixture", () => {
  test("binary expected profit and variance match by value, for strings and Decimals", () => {
    expect(fixture.binary).toHaveLength(5);
    for (const c of fixture.binary) {
      for (const convert of [(x: string) => x, (x: string) => new Decimal(x)]) {
        const e = expectedProfit(convert(c.stake), convert(c.p), convert(c.o));
        const v = profitVariance(convert(c.stake), convert(c.p), convert(c.o));
        expect(Decimal.isDecimal(e) && Decimal.isDecimal(v), c.name).toBe(true);
        expect(e.eq(c.expected_profit), `${c.name}: ${e.toFixed()}`).toBe(true);
        expect(v.eq(c.variance), `${c.name}: ${v.toFixed()}`).toBe(true);
      }
    }
  });

  test("the brief's vector is exactly 5.0005", () => {
    expect(expectedProfit("100", "0.55", "1.9091").toFixed()).toBe("5.0005");
  });

  test("outcome moments match by value", () => {
    expect(fixture.outcomes).toHaveLength(3);
    for (const c of fixture.outcomes) {
      const [mean, variance] = outcomeMoments(c.stake, c.price, toOutcomes(c.outcomes));
      expect(mean.eq(c.mean), `${c.name}: ${mean.toFixed()}`).toBe(true);
      expect(variance.eq(c.variance), `${c.name}: ${variance.toFixed()}`).toBe(true);
    }
  });

  test("the push case with the named settlements", () => {
    const [mean, variance] = outcomeMoments("10", "2.0", [
      ["0.45", WIN],
      ["0.10", VOID],
      ["0.45", LOSS],
    ]);
    expect(mean.eq(0)).toBe(true);
    expect(variance.eq(90)).toBe(true);
  });

  test("the cumulative band matches: exact running sums, sigma as the same double as Python", () => {
    expect(fixture.band).toHaveLength(3);
    for (const c of fixture.band) {
      const got = cumulativeBand(c.bets.map(([e, v]) => [new Decimal(e), new Decimal(v)]));
      expect(got, c.name).toHaveLength(c.points.length);
      got.forEach((point, i) => {
        const want = c.points[i];
        expect(Decimal.isDecimal(point.expected), c.name).toBe(true);
        expect(point.expected.eq(want.expected), `${c.name}[${i}]: ${point.expected.toFixed()}`).toBe(true);
        expect(point.sigma, `${c.name}[${i}]`).toBe(want.sigma);
      });
    }
  });

  test("the running sum is exact past 40 digits", () => {
    const band = cumulativeBand([
      [new Decimal("100000000000000000000"), new Decimal(2)],
      [new Decimal("0.000000000000000000001"), new Decimal(0)],
    ]);
    expect(band[1].expected.toFixed()).toBe("100000000000000000000.000000000000000000001");
  });

  test("a band of the fixture bets sums their moments", () => {
    const bets = fixture.binary.map((c) => [expectedProfit(c.stake, c.p, c.o), profitVariance(c.stake, c.p, c.o)] as [Decimal, Decimal]);
    const Wide = Decimal.clone({ precision: 200 });
    const totalE = bets.reduce((s, [e]) => s.plus(e), new Wide(0));
    const totalV = bets.reduce((s, [, v]) => s.plus(v), new Wide(0));
    const band = cumulativeBand(bets);
    expect(band[band.length - 1].expected.eq(totalE)).toBe(true);
    expect(band[band.length - 1].sigma).toBe(Math.sqrt(Number(totalV)));
  });

  test("zero is never negative zero", () => {
    const [point] = cumulativeBand([[new Decimal("-0"), new Decimal("-0")]]);
    expect(point.expected.isZero() && !point.expected.isNegative()).toBe(true);
    expect(Object.is(point.sigma, 0)).toBe(true);
  });
});

describe("expected: properties", () => {
  test("binary formulas equal outcomeMoments over WIN with p and LOSS with 1 - p (200 random cases)", () => {
    const r = rng(20261102);
    for (let i = 0; i < 200; i++) {
      const stake = `${randInt(r, 0, 5000)}.${String(randInt(r, 0, 99)).padStart(2, "0")}`;
      const p = r() < 0.95 ? `0.${String(randInt(r, 0, 999999)).padStart(6, "0")}` : r() < 0.5 ? "0" : "1";
      const q = new Decimal(1).minus(p).toFixed(); // exact: few digits
      const o = `${randInt(r, 1, 200)}.${String(randInt(r, 1, 9999)).padStart(4, "0")}`;
      const [mean, variance] = outcomeMoments(stake, o, [
        [p, WIN],
        [q, LOSS],
      ]);
      const label = `${stake} ${p} ${o}`;
      expect(profitVariance(stake, p, o).eq(variance), label).toBe(true);
      expect(expectedProfit(stake, p, o).eq(mean), label).toBe(true);
    }
  });

  test("every settlement shape gives a non-negative variance", () => {
    const r = rng(7);
    const shapes = [WIN, LOSS, VOID, HALF_WIN, HALF_LOSS, settlement("1/3", "0/1")];
    for (let i = 0; i < 100; i++) {
      const stake = `${randInt(r, 0, 1000)}.${String(randInt(r, 0, 99)).padStart(2, "0")}`;
      const o = `${randInt(r, 1, 50)}.${String(randInt(r, 1, 999)).padStart(3, "0")}`;
      const qs = shapes.slice(0, -1).map(() => new Decimal(randInt(r, 0, 150)).div(1000));
      const last = new Decimal(1).minus(qs.reduce((s, x) => s.plus(x), new Decimal(0)));
      const outcomes = [...qs, last].map((q, k) => [q, shapes[k]] as [Decimal, Settlement]);
      const [, variance] = outcomeMoments(stake, o, outcomes);
      expect(variance.isNegative() && !variance.isZero()).toBe(false);
    }
  });
});

describe("expected: validation", () => {
  test.each<string[]>([["0.5", "0.49"], ["0.5", "0.51"], ["0.3333333333", "0.3333333333", "0.3333333333"], ["0.5", "0.5", "0.0000000001"], ["0.99"]])(
    "outcomes must sum to exactly 1 (%s)",
    (...probs) => {
      const outcomes = probs.map((q, i) => [q, i === 0 ? WIN : LOSS] as [string, Settlement]);
      expect(() => outcomeMoments("10", "2", outcomes)).toThrow(/sum to exactly 1/);
      expect(() => outcomeMoments("10", "2", outcomes)).toThrow(RangeError);
    },
  );

  test("outcomes summing to exactly 1 are accepted", () => {
    const [m1, v1] = outcomeMoments("10", "2", [["1", WIN]]);
    expect(m1.eq(10) && v1.eq(0)).toBe(true);
    const [m2] = outcomeMoments("10", "2", [
      ["0.1", WIN],
      ["0.2", LOSS],
      ["0.7", LOSS],
    ]);
    expect(m2.eq(-8)).toBe(true);
  });

  test("no outcomes is rejected", () => {
    expect(() => outcomeMoments("10", "2", [])).toThrow(RangeError);
  });

  test.each(["1.1", new Decimal("-0.1"), new Decimal("1.0000001")])("an outcome probability outside [0, 1] is rejected (%s)", (bad) => {
    expect(() => outcomeMoments("10", "2", [[bad, WIN]])).toThrow(RangeError);
  });

  test.each([null, undefined, "win", [1n, 0n], { win: [1n, 1n] }, { win: [1, 1], refund: [0, 1] }])(
    "an outcome settlement that is not a Settlement is a TypeError (%s)",
    (bad) => {
      const call = () => outcomeMoments("10", "2", [["1", bad as unknown as Settlement]]);
      expect(call).toThrow(TypeError);
      expect(call).toThrow(/must be a Settlement/);
    },
  );

  test("an invalid settlement value is a RangeError", () => {
    const bad = { win: [2n, 1n], refund: [0n, 1n] } as unknown as Settlement;
    expect(() => outcomeMoments("10", "2", [["1", bad]])).toThrow(RangeError);
  });

  test.each([null, undefined, "1", 5, {}, [["1"]], [["1", WIN, WIN]], ["1"]])("outcomes must be an array of pairs (%s)", (bad) => {
    const call = () => outcomeMoments("10", "2", bad as unknown as Array<[string, Settlement]>);
    expect(call).toThrow(TypeError);
    expect(call).toThrow(/outcomes must be/);
  });

  const BAD_NUMBERS: unknown[] = [
    null,
    undefined,
    true,
    1,
    1.5,
    10n,
    new Decimal(NaN),
    new Decimal(Infinity),
    "",
    " 1",
    "1 ",
    "1\n",
    "+1",
    "-1",
    "1e2",
    "1_0",
    ".5",
    "5.",
    "NaN",
    "Infinity",
    new Decimal("1e30"),
    new Decimal("1e-61"),
  ];

  test.each(BAD_NUMBERS)("a bad stake is a RangeError (%s)", (bad) => {
    expect(() => expectedProfit(bad as string, "0.5", "2")).toThrow(RangeError);
    expect(() => profitVariance(bad as string, "0.5", "2")).toThrow(RangeError);
    expect(() => outcomeMoments(bad as string, "2", [["1", WIN]])).toThrow(RangeError);
  });

  test.each(BAD_NUMBERS)("a bad probability is a RangeError (%s)", (bad) => {
    expect(() => expectedProfit("10", bad as string, "2")).toThrow(RangeError);
    expect(() => profitVariance("10", bad as string, "2")).toThrow(RangeError);
    expect(() => outcomeMoments("10", "2", [[bad as string, WIN]])).toThrow(RangeError);
  });

  test.each(BAD_NUMBERS)("a bad price is a RangeError (%s)", (bad) => {
    expect(() => expectedProfit("10", "0.5", bad as string)).toThrow(RangeError);
    expect(() => profitVariance("10", "0.5", bad as string)).toThrow(RangeError);
    expect(() => outcomeMoments("10", bad as string, [["1", WIN]])).toThrow(RangeError);
  });

  test.each([expectedProfit, profitVariance])("value ranges (%o)", (fn) => {
    expect(() => fn(new Decimal(-1), "0.5", "2")).toThrow(/stake/);
    expect(() => fn("10", new Decimal("-0.1"), "2")).toThrow(/fairProb/);
    expect(() => fn("10", "1.1", "2")).toThrow(/fairProb/);
    for (const price of ["1", "0.5", "0"]) expect(() => fn("10", "0.5", price)).toThrow(/price/);
    expect(fn("0", "0.5", "2").isZero()).toBe(true);
  });

  test("outcomeMoments value ranges", () => {
    expect(() => outcomeMoments(new Decimal(-1), "2", [["1", WIN]])).toThrow(/stake/);
    expect(() => outcomeMoments("10", "1", [["1", WIN]])).toThrow(/price/);
  });

  test.each<[string, unknown]>([
    ["strings are not accepted here", [["5", "9"]]],
    ["numbers", [[5, 9]]],
    ["NaN", [[new Decimal(NaN), new Decimal(1)]]],
    ["infinite variance", [[new Decimal(1), new Decimal(Infinity)]]],
    ["negative variance", [[new Decimal(1), new Decimal(-1)]]],
    ["out of the money domain", [[new Decimal("1e30"), new Decimal(1)]]],
    ["too small", [[new Decimal(1), new Decimal("1e-61")]]],
  ])("the band rejects bad values with a RangeError: %s", (_, bad) => {
    expect(() => cumulativeBand(bad as Array<[Decimal, Decimal]>)).toThrow(RangeError);
  });

  test.each<[string, unknown]>([
    ["one value", [[new Decimal(1)]]],
    ["three values", [[new Decimal(1), new Decimal(1), new Decimal(1)]]],
    ["a bare Decimal", [new Decimal(1)]],
    ["null", null],
    ["a string", "bets"],
  ])("the band rejects a bad shape with a TypeError: %s", (_, bad) => {
    const call = () => cumulativeBand(bad as Array<[Decimal, Decimal]>);
    expect(call).toThrow(TypeError);
    expect(call).toThrow(/bets must be/);
  });

  test("the band accepts a negative expected profit", () => {
    const band = cumulativeBand([
      [new Decimal("-1.5"), new Decimal(0)],
      [new Decimal("-0.5"), new Decimal("0.25")],
    ]);
    expect(band.map((p) => p.expected.toFixed())).toEqual(["-1.5", "-2"]);
    expect(band.map((p) => p.sigma)).toEqual([0, 0.5]);
  });
});
