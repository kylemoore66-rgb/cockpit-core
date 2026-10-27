import { createHash } from "node:crypto";
import { describe, expect, test } from "vitest";
import {
  GENESIS,
  chainRoot,
  dayRoot,
  fromHex,
  inclusionProof,
  merkleRoot,
  rowHash,
  toHex,
  verifyInclusion,
} from "../src/index.js";
import { cases } from "./cases.js";

const enc = new TextEncoder();
const leaves = (strings: string[]): Uint8Array[] => strings.map((s) => enc.encode(s));
const sha = (...parts: Uint8Array[]): Uint8Array => {
  const h = createHash("sha256");
  for (const p of parts) h.update(p);
  return new Uint8Array(h.digest());
};
const flip = (b: Uint8Array): Uint8Array => {
  const c = Uint8Array.from(b);
  c[0] ^= 0x01;
  return c;
};
const be64 = (n: number): Uint8Array => {
  const b = new Uint8Array(8);
  new DataView(b.buffer).setBigUint64(0, BigInt(n));
  return b;
};
const bytes = (n: number, fill = 0): Uint8Array => new Uint8Array(n).fill(fill);

describe("constants and hex", () => {
  test("GENESIS is 32 zero bytes", () => {
    expect(GENESIS).toEqual(new Uint8Array(32));
  });

  test("hex round-trips", () => {
    expect(toHex(Uint8Array.of(0, 1, 0xab, 0xff))).toBe("0001abff");
    expect(fromHex("0001abff")).toEqual(Uint8Array.of(0, 1, 0xab, 0xff));
    expect(fromHex("ABFF")).toEqual(Uint8Array.of(0xab, 0xff));
    expect(fromHex("")).toEqual(new Uint8Array(0));
  });

  test.each(["0", "0g", "zz", " 00", "00 ", "0x00", "+0"])("bad hex is a RangeError (%j)", (bad) => {
    expect(() => fromHex(bad)).toThrow(RangeError);
  });

  test.each([null, 0, [0], new Uint8Array(1)])("non-string hex is a TypeError (%s)", (bad) => {
    expect(() => fromHex(bad as unknown as string)).toThrow(TypeError);
  });

  test.each([null, "00", [0], new ArrayBuffer(1)])("toHex of a non-Uint8Array is a TypeError (%s)", (bad) => {
    expect(() => toHex(bad as unknown as Uint8Array)).toThrow(TypeError);
  });
});

describe("row hashes", () => {
  test("row hash is sha256(salt || canonical)", () => {
    const salt = Uint8Array.from({ length: 16 }, (_, i) => i);
    expect(rowHash(salt, enc.encode("x"))).toEqual(sha(salt, enc.encode("x")));
  });

  test.each([0, 15, 17, 32])("salt of %i bytes is a RangeError", (n) => {
    expect(() => rowHash(bytes(n), enc.encode("{}"))).toThrow(RangeError);
  });

  test.each<[unknown, unknown]>([
    ["0".repeat(16), enc.encode("{}")],
    [bytes(16), "{}"],
    [bytes(16), null],
    [Array.from(bytes(16)), enc.encode("{}")],
  ])("non-Uint8Array arguments are a TypeError", (salt, canonical) => {
    expect(() => rowHash(salt as Uint8Array, canonical as Uint8Array)).toThrow(TypeError);
  });
});

describe("Merkle roots", () => {
  test("roots match fixture", () => {
    expect(cases.merkle.roots).toHaveLength(5);
    for (const fx of cases.merkle.roots) {
      expect(toHex(merkleRoot(leaves(fx.leaves))), JSON.stringify(fx.leaves)).toBe(fx.root);
    }
  });

  test("empty tree is sha256 of nothing", () => {
    expect(merkleRoot([])).toEqual(sha());
  });

  test("RFC 6962 shape", () => {
    const leaf = (d: Uint8Array) => sha(Uint8Array.of(0), d);
    const node = (l: Uint8Array, r: Uint8Array) => sha(Uint8Array.of(1), l, r);
    const [a, b, c, d, e] = leaves(["a", "b", "c", "d", "e"]).map(leaf);
    expect(merkleRoot(leaves(["a", "b", "c", "d", "e"]))).toEqual(node(node(node(a, b), node(c, d)), e));
    expect(merkleRoot(leaves(["a", "b", "c"]))).toEqual(node(node(a, b), c));
  });

  test.each([["a"], [enc.encode("a"), "b"], [null], "ab", enc.encode("ab"), null, undefined])(
    "non-Uint8Array leaves are a TypeError (%s)",
    (bad) => {
      expect(() => merkleRoot(bad as unknown as Uint8Array[])).toThrow(TypeError);
    },
  );
});

describe("inclusion proofs", () => {
  const fx = cases.merkle.inclusion;
  const ls = leaves(fx.leaves);
  const i: number = fx.index;
  const n = ls.length;
  const root = merkleRoot(ls);

  test("proof matches fixture and verifies", () => {
    const proof = inclusionProof(ls, i);
    expect(proof.map(toHex)).toEqual(fx.proof);
    expect(verifyInclusion(ls[i], i, n, proof, root)).toBe(true);
    for (let k = 0; k < proof.length; k++) {
      const tampered = [...proof];
      tampered[k] = flip(tampered[k]);
      expect(verifyInclusion(ls[i], i, n, tampered, root)).toBe(false);
    }
    for (const idx of [0, 1, 3, 4, n, n + 1, -1]) {
      expect(verifyInclusion(ls[i], idx, n, proof, root)).toBe(false);
    }
  });

  test("wrong leaf, root, size or proof length gives false", () => {
    const proof = inclusionProof(ls, i);
    expect(verifyInclusion(enc.encode("z"), i, n, proof, root)).toBe(false);
    expect(verifyInclusion(ls[i], i, n, proof, flip(root))).toBe(false);
    expect(verifyInclusion(ls[i], i, n - 1, proof, root)).toBe(false);
    expect(verifyInclusion(ls[i], i, 0, proof, root)).toBe(false);
    expect(verifyInclusion(ls[i], i, -1, proof, root)).toBe(false);
    expect(verifyInclusion(ls[i], i, n, proof.slice(0, -1), root)).toBe(false);
    expect(verifyInclusion(ls[i], i, n, [...proof, proof[0]], root)).toBe(false);
    expect(verifyInclusion(ls[i], i, n, [], root)).toBe(false);
    expect(verifyInclusion(ls[i], i, n, [...proof].reverse(), root)).toBe(false);
    expect(verifyInclusion(ls[i], i, n, [proof[0].slice(0, 31), ...proof.slice(1)], root)).toBe(false);
    expect(verifyInclusion(ls[i], i, n, [Uint8Array.of(...proof[0], 0), ...proof.slice(1)], root)).toBe(false);
  });

  test("the root alone does not commit the tree size (RFC 9162, pinned)", () => {
    expect(verifyInclusion(ls[i], i, n + 1, inclusionProof(ls, i), root)).toBe(true);
  });

  test("bigint index and tree size work too", () => {
    expect(verifyInclusion(ls[i], BigInt(i), BigInt(n), inclusionProof(ls, i), root)).toBe(true);
    expect(verifyInclusion(ls[i], i, 2 ** 60, inclusionProof(ls, i), root)).toBe(false);
  });

  test.each(Array.from({ length: 17 }, (_, k) => k + 1))("round-trips for every index of %i leaves", (size) => {
    const ls2 = Array.from({ length: size }, (_, j) => enc.encode(`leaf-${j}`));
    const r = merkleRoot(ls2);
    for (let a = 0; a < size; a++) {
      const proof = inclusionProof(ls2, a);
      expect(verifyInclusion(ls2[a], a, size, proof, r)).toBe(true);
      for (let b = 0; b < size; b++) {
        if (b !== a) {
          expect(verifyInclusion(ls2[a], b, size, proof, r)).toBe(false);
          expect(verifyInclusion(ls2[b], a, size, proof, r)).toBe(false);
        }
      }
    }
  });

  test("single-leaf tree has an empty proof", () => {
    const only = enc.encode("only");
    const r = merkleRoot([only]);
    expect(inclusionProof([only], 0)).toEqual([]);
    expect(verifyInclusion(only, 0, 1, [], r)).toBe(true);
    expect(verifyInclusion(only, 0, 1, [r], r)).toBe(false);
  });

  test.each([-1, 5, 6, 2.5, NaN])("inclusionProof index out of range is a RangeError (%s)", (index) => {
    expect(() => inclusionProof(ls, index)).toThrow(RangeError);
  });

  test.each([true, "2", null, undefined])("inclusionProof index of the wrong type is a TypeError (%s)", (index) => {
    expect(() => inclusionProof(ls, index as unknown as number)).toThrow(TypeError);
  });

  test("inclusionProof of an empty tree is a RangeError", () => {
    expect(() => inclusionProof([], 0)).toThrow(RangeError);
  });

  test.each<[string, unknown[]]>([
    ["leaf is a string", ["a", 0, 1, [], bytes(32)]],
    ["index is a boolean", [enc.encode("a"), true, 1, [], bytes(32)]],
    ["tree size is a string", [enc.encode("a"), 0, "1", [], bytes(32)]],
    ["proof element is a string", [enc.encode("a"), 0, 1, ["00".repeat(32)], bytes(32)]],
    ["proof is bytes, not an array", [enc.encode("a"), 0, 1, bytes(32), bytes(32)]],
    ["root is a string", [enc.encode("a"), 0, 1, [], "00".repeat(32)]],
  ])("verifyInclusion throws TypeError only for wrong types: %s", (_name, args) => {
    expect(() => (verifyInclusion as (...a: unknown[]) => boolean)(...args)).toThrow(TypeError);
  });

  test.each<[string, unknown[]]>([
    ["root is 31 bytes", [enc.encode("a"), 0, 1, [], bytes(31)]],
    ["index is fractional", [enc.encode("a"), 0.5, 1, [], bytes(32)]],
    ["tree size is NaN", [enc.encode("a"), 0, NaN, [], bytes(32)]],
  ])("verifyInclusion throws RangeError for a wrong-size root or non-integer number: %s", (_name, args) => {
    expect(() => (verifyInclusion as (...a: unknown[]) => boolean)(...args)).toThrow(RangeError);
  });
});

describe("chained batch roots and day roots", () => {
  test("chain and day roots match fixture", () => {
    expect(cases.merkle.chain).toHaveLength(2);
    expect(cases.merkle.day).toHaveLength(2);
    let prev: Uint8Array | undefined;
    for (const fx of cases.merkle.chain) {
      expect(["genesis", "previous"]).toContain(fx.prev);
      const start = fx.prev === "genesis" ? GENESIS : prev;
      expect(start).toBeDefined();
      prev = chainRoot(start!, merkleRoot(leaves(fx.batch_leaves)), fx.n_rows);
      expect(toHex(prev)).toBe(fx.chained);
    }
    prev = undefined;
    for (const fx of cases.merkle.day) {
      expect(["genesis", "previous"]).toContain(fx.prev);
      const start = fx.prev === "genesis" ? GENESIS : prev;
      expect(start).toBeDefined();
      prev = dayRoot(start!, fx.chained_roots.map(fromHex));
      expect(toHex(prev)).toBe(fx.day_root);
    }
  });

  test("chain and day root formulas", () => {
    const prev = Uint8Array.from({ length: 32 }, (_, k) => k);
    const batch = Uint8Array.from({ length: 32 }, (_, k) => k + 32);
    expect(chainRoot(prev, batch, 3)).toEqual(sha(enc.encode("cockpit-chain-v1"), prev, batch, be64(3)));
    expect(chainRoot(prev, batch, 3n)).toEqual(chainRoot(prev, batch, 3));
    const roots = [bytes(32, 7), bytes(32, 9)];
    expect(dayRoot(prev, roots)).toEqual(sha(enc.encode("cockpit-day-v1"), prev, merkleRoot(roots), be64(2)));
  });

  test("n_rows is 8 bytes big-endian up to 2**64 - 1", () => {
    const max = 2n ** 64n - 1n;
    const expected = sha(enc.encode("cockpit-chain-v1"), GENESIS, GENESIS, bytes(8, 0xff));
    expect(chainRoot(GENESIS, GENESIS, max)).toEqual(expected);
  });

  test("day root order matters", () => {
    const a = bytes(32, 1);
    const b = bytes(32, 2);
    expect(dayRoot(GENESIS, [a, b])).not.toEqual(dayRoot(GENESIS, [b, a]));
  });

  test.each<[string, unknown, unknown, unknown]>([
    ["prev 31 bytes", bytes(31), bytes(32), 1],
    ["batch 33 bytes", bytes(32), bytes(33), 1],
    ["negative rows", bytes(32), bytes(32), -1],
    ["rows 2**64", bytes(32), bytes(32), 2n ** 64n],
    ["rows 2**64 as a number", bytes(32), bytes(32), 2 ** 64],
    ["fractional rows", bytes(32), bytes(32), 1.5],
    ["NaN rows", bytes(32), bytes(32), NaN],
  ])("chainRoot rejects bad values with RangeError: %s", (_name, prev, batch, nRows) => {
    expect(() => chainRoot(prev as Uint8Array, batch as Uint8Array, nRows as number)).toThrow(RangeError);
  });

  test.each<[string, unknown, unknown, unknown]>([
    ["prev is hex", "00".repeat(32), bytes(32), 1],
    ["rows is a boolean", bytes(32), bytes(32), true],
    ["rows is a string", bytes(32), bytes(32), "1"],
  ])("chainRoot rejects wrong types with TypeError: %s", (_name, prev, batch, nRows) => {
    expect(() => chainRoot(prev as Uint8Array, batch as Uint8Array, nRows as number)).toThrow(TypeError);
  });

  test("dayRoot rejects bad inputs", () => {
    expect(() => dayRoot(bytes(31), [])).toThrow(RangeError);
    expect(() => dayRoot(bytes(32), [bytes(31)])).toThrow(RangeError);
    expect(() => dayRoot("00".repeat(32) as unknown as Uint8Array, [])).toThrow(TypeError);
    expect(() => dayRoot(bytes(32), [bytes(32), "00".repeat(32) as unknown as Uint8Array])).toThrow(TypeError);
    expect(() => dayRoot(bytes(32), bytes(64) as unknown as Uint8Array[])).toThrow(TypeError);
  });
});
