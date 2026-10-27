// The single division must be exact truncation to 40 significant digits, as Python's
// Decimal(n) / Decimal(d) is under prec=40, rounding=ROUND_DOWN. This checks decimal.js against a
// pure-bigint long-division reference on adversarial and pseudo-random inputs.
import { expect, test } from "vitest";
import { type Rational, divideOnce, exactMoney } from "../src/_exact.js";

const LIMIT = 10n ** 40n;

/** n / d truncated toward zero to 40 significant digits, as t * 10^-k. */
function reference(n: bigint, d: bigint): Rational {
  const neg = n < 0n;
  const a = neg ? -n : n;
  if (a === 0n) return { n: 0n, d: 1n };
  let k = 40 - (a.toString().length - d.toString().length);
  const at = (kk: number): bigint => (kk >= 0 ? (a * 10n ** BigInt(kk)) / d : a / (d * 10n ** BigInt(-kk)));
  let t = at(k);
  while (t >= LIMIT) t = at(--k);
  while (t < LIMIT / 10n) t = at(++k);
  const signed = neg ? -t : t;
  return k >= 0 ? { n: signed, d: 10n ** BigInt(k) } : { n: signed * 10n ** BigInt(-k), d: 1n };
}

/** Exact rational of a non-negative quotient (not exactMoney: quotients here go far past the money limit). */
function toRational(q: { toFixed(): string }): Rational {
  const [whole, frac = ""] = q.toFixed().split(".");
  return { n: BigInt(whole + frac), d: 10n ** BigInt(frac.length) };
}

function sameValue(n: bigint, d: bigint): void {
  const got = toRational(divideOnce({ n, d }).abs());
  const want = reference(n < 0n ? -n : n, d);
  expect(got.n * want.d, `${n}/${d}`).toBe(want.n * got.d);
  if (n < 0n) expect(divideOnce({ n, d }).isNegative()).toBe(true);
}

// Deterministic xorshift so failures reproduce.
let seed = 0x2545f491n;
function nextBig(digits: number): bigint {
  let s = "";
  while (s.length < digits) {
    seed ^= (seed << 13n) & 0xffffffffffffffffn;
    seed ^= seed >> 7n;
    seed ^= (seed << 17n) & 0xffffffffffffffffn;
    s += seed.toString();
  }
  return BigInt(s.slice(0, digits));
}

test("divideOnce truncates exactly like a bigint long division", () => {
  const edges: [bigint, bigint][] = [
    [5n, 3n],
    [21n, 11n],
    [-1n, 3000n],
    [10n ** 47n - 1n, 10n ** 49n], // 0.00999...9 (47 nines after the point)
    [10n ** 63n * 4n + 10n ** 63n - 1n, 10n ** 66n], // 0.004999...9
    [-(10n ** 63n * 4n + 10n ** 63n - 1n), 10n ** 66n],
    [2n * 10n ** 45n - 1n, 2n * 10n ** 45n],
    [1n, 7n ** 60n],
  ];
  for (const [n, d] of edges) sameValue(n, d);
  for (let i = 0; i < 3000; i++) {
    const n = nextBig(1 + (i % 70)) * (i % 3 === 0 ? -1n : 1n);
    const d = nextBig(1 + ((i * 7) % 55)) + 1n;
    sameValue(n, d);
  }
});

test("exactMoney reads Decimals and strict strings exactly", () => {
  expect(exactMoney("x", "0.25")).toEqual({ n: 25n, d: 100n });
  expect(exactMoney("x", "10000")).toEqual({ n: 10000n, d: 1n });
  for (const bad of ["-1", "+1", "1e3", ".5", "5.", "1_000", "", " 1", "0x10", "Infinity", "NaN", "١"]) {
    expect(() => exactMoney("x", bad), bad).toThrow(RangeError);
  }
  for (const bad of [1, 1n, true, null, undefined, {}, [1]]) {
    expect(() => exactMoney("x", bad)).toThrow(RangeError);
  }
});
