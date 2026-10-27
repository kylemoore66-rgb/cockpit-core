import { describe, expect, test } from "vitest";
import {
  type CanonicalPrediction,
  Decimal,
  canonicalBytes,
  fmtPrice,
  fmtProb,
  fmtTs,
  fromHex,
  rowHash,
  toHex,
} from "../src/index.js";
import { cases } from "./cases.js";

type FixturePrediction = {
  model_version: string;
  sport: string;
  event: string;
  market: string;
  selection: string;
  fair_prob: number;
  paper_price: string;
  paper_book: string;
  predicted_at: string;
  features_summary: Record<string, string>;
};

function build(pred: FixturePrediction): CanonicalPrediction {
  return {
    modelVersion: pred.model_version,
    sport: pred.sport,
    event: pred.event,
    market: pred.market,
    selection: pred.selection,
    fairProb: pred.fair_prob,
    paperPrice: pred.paper_price,
    paperBook: pred.paper_book,
    predictedAt: new Date(pred.predicted_at),
    featuresSummary: pred.features_summary,
  };
}

function basic(changes: Record<string, unknown> = {}): CanonicalPrediction {
  return { ...build(cases.canonical.basic.prediction), ...changes } as CanonicalPrediction;
}

const decode = (b: Uint8Array): string => new TextDecoder("utf-8", { fatal: true }).decode(b);
const NFD_ABERG = "Åberg";

describe("canonical fixtures", () => {
  test.each(["basic", "unicode", "millis"])("%s: bytes and row hash match", (name) => {
    const fx = cases.canonical[name];
    const out = canonicalBytes(build(fx.prediction));
    expect(out).toBeInstanceOf(Uint8Array);
    expect(decode(out)).toBe(fx.canonical);
    expect(toHex(rowHash(fromHex(fx.salt_hex), out))).toBe(fx.row_hash);
  });

  test("fixture section has exactly the three cases", () => {
    expect(Object.keys(cases.canonical).sort()).toEqual(["basic", "millis", "unicode"]);
  });

  test("unicode is raw UTF-8, never \\u escapes", () => {
    const out = canonicalBytes(build(cases.canonical.unicode.prediction));
    expect(decode(out)).not.toContain("\\u");
    expect(decode(out)).toContain("Åberg");
  });

  test("keys are the snake_case Python field names", () => {
    const obj = JSON.parse(decode(canonicalBytes(basic())));
    expect(Object.keys(obj)).toEqual([
      "event",
      "fair_prob",
      "features_summary",
      "market",
      "model_version",
      "paper_book",
      "paper_price",
      "predicted_at",
      "selection",
      "sport",
    ]);
  });
});

describe("formatting", () => {
  test("formatting matches fixture", () => {
    expect(cases.formatting).toHaveLength(4);
    const fns: Record<string, (x: number | string) => string> = { prob: fmtProb, price: fmtPrice };
    for (const c of cases.formatting) {
      const kind = "float" in c ? "float" : "str";
      expect(typeof c[kind]).toBe(kind === "float" ? "number" : "string");
      expect(fns[c.fn](c[kind]), JSON.stringify(c)).toBe(c.out);
    }
  });

  test("prob and price formatting", () => {
    expect(fmtProb(0.1834)).toBe("0.183400");
    expect(fmtProb(0.1234565)).toBe("0.123457");
    expect(fmtProb("0.5")).toBe("0.500000");
    expect(fmtProb(new Decimal("0.1234565"))).toBe("0.123457");
    expect(fmtProb("0.1234565")).toBe("0.123457");
    expect(fmtPrice("6.5")).toBe("6.5000");
    expect(fmtPrice("6.50")).toBe("6.5000");
    expect(fmtPrice("2")).toBe("2.0000");
    expect(fmtPrice(2)).toBe("2.0000");
    expect(fmtPrice(2.00005)).toBe("2.0001");
    expect(fmtPrice(new Decimal("1.5"))).toBe("1.5000");
    expect(fmtPrice(1e21)).toBe("1000000000000000000000.0000"); // never exponent notation
    expect(fmtProb(1e-6)).toBe("0.000001");
  });

  test.each([0, -0, -0.1, 1.5, 1.0, 0.9999999, 0.0000004, NaN, Infinity, -Infinity, "abc", ""])(
    "bad probability rejected (%s)",
    (bad) => {
      expect(() => fmtProb(bad as unknown as number)).toThrow(RangeError);
    },
  );

  test.each([1, 1.0, 0.5, -3, 1.00004, -0, NaN, Infinity, "abc", "", "1", "1.00004"])(
    "bad price rejected (%s)",
    (bad) => {
      expect(() => fmtPrice(bad as unknown as number)).toThrow(RangeError);
    },
  );

  test.each([true, false, null, undefined, 1n, {}, [], [0.5], new String("0.5"), new Number(0.5)])(
    "a probability or price of the wrong JS type is a TypeError (%s)",
    (bad) => {
      expect(() => fmtProb(bad as unknown as number)).toThrow(TypeError);
      expect(() => fmtPrice(bad as unknown as number)).toThrow(TypeError);
      expect(() => canonicalBytes(basic({ fairProb: bad }))).toThrow(TypeError);
      expect(() => canonicalBytes(basic({ paperPrice: bad }))).toThrow(TypeError);
    },
  );

  test.each([new Decimal(NaN), new Decimal(Infinity), new Decimal(0), new Decimal(1), new Decimal("-0.5")])(
    "bad Decimal probability rejected (%s)",
    (bad) => {
      expect(() => fmtProb(bad)).toThrow(RangeError);
    },
  );

  test.each([" 0.5", "0.5\n", "０.５", "٠.٥", "1.834E-1", "0x1A", ".5", "5.", "+0.5", "-0.5", "0.18_34", ""])(
    "probability string outside the grammar rejected (%j)",
    (bad) => {
      expect(() => fmtProb(bad)).toThrow(RangeError);
    },
  );

  test.each([" 6.5", "6.5 ", "6.5\n", "６.５", "٦.٥", "6.5E0", "65e-1", "0x1A", "0b101", "0o7", "2.", "+6.5", "6_5", "6.5_0", "Infinity", ""])(
    "price string outside the grammar rejected (%j)",
    (bad) => {
      expect(() => fmtPrice(bad)).toThrow(RangeError);
    },
  );

  test("price beyond 60 significant digits at 4 dp is rejected, as Python's quantize does", () => {
    expect(fmtPrice("1" + "0".repeat(55))).toBe("1" + "0".repeat(55) + ".0000"); // 60 digits: fine
    expect(() => fmtPrice("1" + "0".repeat(56))).toThrow(RangeError); // 61 digits
    expect(() => fmtPrice("9".repeat(56) + ".99995")).toThrow(RangeError); // rounds up to 61 digits
    expect(() => fmtPrice(1e56)).toThrow(RangeError);
  });
});

describe("timestamps", () => {
  test("fmtTs emits .mmmZ", () => {
    expect(fmtTs(new Date("2026-10-29T13:05:07.123Z"))).toBe("2026-10-29T13:05:07.123Z");
    expect(fmtTs(new Date(Date.UTC(2026, 0, 2, 3, 4, 5)))).toBe("2026-01-02T03:04:05.000Z");
    expect(fmtTs(new Date("0001-01-01T00:00:00.000Z"))).toBe("0001-01-01T00:00:00.000Z");
    expect(fmtTs(new Date("9999-12-31T23:59:59.999Z"))).toBe("9999-12-31T23:59:59.999Z");
  });

  test("an invalid Date or a year Python cannot hold is a RangeError", () => {
    expect(() => fmtTs(new Date(Number.NaN))).toThrow(RangeError);
    expect(() => fmtTs(new Date("0000-12-31T23:59:59.999Z"))).toThrow(RangeError);
    expect(() => fmtTs(new Date("+010000-01-01T00:00:00.000Z"))).toThrow(RangeError);
  });

  test.each(["2026-10-29T13:05:07.123Z", 1793000000000, null, undefined, {}])("non-Date is a TypeError (%s)", (bad) => {
    expect(() => fmtTs(bad as unknown as Date)).toThrow(TypeError);
  });
});

describe("text", () => {
  test("NFD text in featuresSummary throws", () => {
    expect(NFD_ABERG.normalize("NFC")).not.toBe(NFD_ABERG);
    expect(() => canonicalBytes(basic({ featuresSummary: { note: NFD_ABERG } }))).toThrow(RangeError);
    expect(() => canonicalBytes(basic({ featuresSummary: { [NFD_ABERG]: "x" } }))).toThrow(RangeError);
    expect(() => canonicalBytes(basic({ selection: NFD_ABERG }))).toThrow(RangeError);
  });

  test.each(["\uD800", "a\uDC00b", "\uDBFF"])("lone surrogates are rejected (%j)", (bad) => {
    expect(() => canonicalBytes(basic({ featuresSummary: { note: bad } }))).toThrow(RangeError);
    expect(() => canonicalBytes(basic({ featuresSummary: { [bad]: "x" } }))).toThrow(RangeError);
    expect(() => canonicalBytes(basic({ event: bad }))).toThrow(RangeError);
  });

  test("astral characters (a well-formed pair) are fine", () => {
    const out = decode(canonicalBytes(basic({ featuresSummary: { note: "\u{1F3CC}\u{FE0F} \u{20000}" } })));
    expect(out).toContain('"note":"\u{1F3CC}\u{FE0F} \u{20000}"');
  });

  test("features keys sort by UTF-16 code units (RFC 8785)", () => {
    // U+1F600 is the pair D83D DE00, which sorts before U+FF61 in UTF-16 though after it by code point.
    const out = decode(canonicalBytes(basic({ featuresSummary: { "｡": "b", "\u{1F600}": "a" } })));
    expect(out).toContain('"features_summary":{"\u{1F600}":"a","｡":"b"}');
  });

  test("__proto__ and toJSON are ordinary keys", () => {
    const features = JSON.parse('{"__proto__":"p","toJSON":"t","constructor":"c"}');
    const out = decode(canonicalBytes(basic({ featuresSummary: features })));
    expect(out).toContain('"features_summary":{"__proto__":"p","constructor":"c","toJSON":"t"}');
  });

  test("integer-like keys sort as strings, not numbers", () => {
    const out = decode(canonicalBytes(basic({ featuresSummary: { "10": "a", "2": "b", "1": "c" } })));
    expect(out).toContain('"features_summary":{"1":"c","10":"a","2":"b"}');
  });

  test("control characters are escaped as RFC 8785 requires", () => {
    const out = decode(canonicalBytes(basic({ featuresSummary: { note: "a\u0000\u001f\n\t\"\\\u007f " } })));
    expect(out).toContain('"note":"a\\u0000\\u001f\\n\\t\\"\\\\\u007f "');
  });

  test("empty featuresSummary is {}", () => {
    expect(decode(canonicalBytes(basic({ featuresSummary: {} })))).toContain('"features_summary":{}');
  });
});

describe("wrong structure", () => {
  test.each([7, null, undefined, new String("golf")])("non-string text field is a TypeError (%s)", (bad) => {
    expect(() => canonicalBytes(basic({ sport: bad }))).toThrow(TypeError);
  });

  test.each([{ x: 1 }, { x: null }, { x: undefined }, { x: ["a"] }, { x: { y: "z" } }])(
    "non-string features value is a TypeError (%j)",
    (bad) => {
      expect(() => canonicalBytes(basic({ featuresSummary: bad }))).toThrow(TypeError);
    },
  );

  test.each([null, undefined, "x", ["a"], new Map([["a", "b"]]), new Date(0)])(
    "featuresSummary that is not a plain object is a TypeError (%s)",
    (bad) => {
      expect(() => canonicalBytes(basic({ featuresSummary: bad }))).toThrow(TypeError);
    },
  );

  test("a null-prototype featuresSummary is accepted", () => {
    const features = Object.assign(Object.create(null) as Record<string, string>, { a: "b" });
    expect(decode(canonicalBytes(basic({ featuresSummary: features })))).toContain('"features_summary":{"a":"b"}');
  });

  test.each([null, undefined, "p", 1])("prediction that is not an object is a TypeError (%s)", (bad) => {
    expect(() => canonicalBytes(bad as unknown as CanonicalPrediction)).toThrow(TypeError);
  });

  test("bad numbers and timestamps inside a prediction are rejected", () => {
    expect(() => canonicalBytes(basic({ fairProb: 1 }))).toThrow(RangeError);
    expect(() => canonicalBytes(basic({ paperPrice: "1.0" }))).toThrow(RangeError);
    expect(() => canonicalBytes(basic({ predictedAt: "2026-10-29T13:05:00Z" }))).toThrow(TypeError);
  });
});
