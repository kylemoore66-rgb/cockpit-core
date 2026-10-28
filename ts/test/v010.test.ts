// v0.1.0 compatibility guard: records with a paper price hash exactly as they did in v0.1.0.
// The predictions and expected hashes are literals, never read from cases.json, so a fixture edit cannot
// hide drift. Mirrors python/tests/test_v010_compat.py.
import { describe, expect, test } from "vitest";
import { type CanonicalPrediction, canonicalBytes, fromHex, rowHash, toHex } from "../src/index.js";

const V010_SALT = fromHex("000102030405060708090a0b0c0d0e0f");

const BASE: CanonicalPrediction = {
  modelVersion: "golf-baseline@1",
  sport: "golf",
  event: "2026-mexico-open",
  market: "2026-mexico-open:top_10",
  selection: "2026-mexico-open:top_10:player-123",
  fairProb: 0.1834,
  paperPrice: "6.5",
  paperBook: "draftkings",
  predictedAt: new Date("2026-10-29T13:05:00Z"),
  featuresSummary: { form_trend: "strong", course_fit: "+" },
};

const V010: Record<string, { prediction: CanonicalPrediction; rowHash: string }> = {
  basic: {
    prediction: BASE,
    rowHash: "feb389ad6d89727d409ee325e6bcfa419a6e05297e5dc71b81ada43c668b0ed2",
  },
  unicode: {
    prediction: { ...BASE, featuresSummary: { note: "Åberg — links form", course_fit: "+" } },
    rowHash: "d176fa8fc345ecdbdb72a63d97e00d664a546f794c0bda484e6870404409fe72",
  },
  millis: {
    prediction: { ...BASE, predictedAt: new Date("2026-10-29T13:05:07.123Z") },
    rowHash: "f5ab48cd357e6a6c049ebc97748c6e7af855c05ade898a5469a7d65150d17d2c",
  },
};

describe("v0.1.0 compatibility", () => {
  test.each(Object.keys(V010))("v0.1.0 row hash is byte-identical (%s)", (name) => {
    const { prediction, rowHash: expected } = V010[name];
    expect(prediction.paperPrice).toBeDefined(); // a v0.1.0 record always carries the pair
    expect(prediction.paperBook).toBeDefined();
    expect(toHex(rowHash(V010_SALT, canonicalBytes(prediction)))).toBe(expected);
  });

  test("all three v0.1.0 vectors are pinned", () => {
    expect(Object.keys(V010).sort()).toEqual(["basic", "millis", "unicode"]);
  });
});

// The v0.2.0 absent-pair vector: a record without a paper price (8 canonical fields). A literal, never read
// from cases.json, pinned like the v0.1.0 hashes above. Mirrors python/tests/test_v010_compat.py.
const V020_ABSENT_PAIR: CanonicalPrediction = {
  modelVersion: "golf-baseline@1",
  sport: "golf",
  event: "2026-mexico-open",
  market: "2026-mexico-open:top_10",
  selection: "2026-mexico-open:top_10:player-123",
  fairProb: 0.1834,
  predictedAt: new Date("2026-10-29T13:05:00Z"),
  featuresSummary: { form_trend: "strong", course_fit: "+" },
};
const V020_ABSENT_PAIR_ROW_HASH = "0d4c4df74722297d0e8a95ad1bce1c12d2548bc81033e7ba38a299621943eb14";

describe("v0.2.0 absent-pair vector", () => {
  test("a record without a paper price hashes to the pinned value", () => {
    expect("paperPrice" in V020_ABSENT_PAIR || "paperBook" in V020_ABSENT_PAIR).toBe(false);
    const bytes = canonicalBytes(V020_ABSENT_PAIR);
    expect(new TextDecoder().decode(bytes)).not.toContain("paper");
    expect(toHex(rowHash(V010_SALT, bytes))).toBe(V020_ABSENT_PAIR_ROW_HASH);
  });
});
