/**
 * Proof primitives: the TS twin of the Python package's `proof.py`, so a browser can recompute every
 * published hash and root.
 *
 * - Hash: SHA-256 everywhere.
 * - Row hash: `sha256(salt || canonical)`, with a 16-byte salt and the bytes from `canonicalBytes`.
 * - Merkle tree: RFC 6962 section 2.1. Leaf `sha256(0x00 || d)`, node `sha256(0x01 || left || right)`,
 *   split at the largest power of two strictly below n. The empty tree's root is `sha256("")`.
 * - Inclusion proof: RFC 6962 `PATH`, ordered leaf to root; verification follows RFC 9162 section 2.1.3.2.
 * - Batch chain: `sha256("cockpit-chain-v1" || prev || batchRoot || nRows as 8-byte big-endian)`.
 * - Day root: `sha256("cockpit-day-v1" || prevDay || merkleRoot(chainedRoots) || count as 8-byte big-endian)`.
 * - Genesis: 32 zero bytes.
 *
 * Errors: an argument of the wrong JS type is a TypeError; one of the right type but the wrong size or
 * range is a RangeError. `verifyInclusion` throws only for those, and returns false for any proof that
 * does not verify, exactly as the Python package does.
 */
import { sha256 } from "@noble/hashes/sha2.js";

export const HASH_SIZE = 32;
export const SALT_SIZE = 16;
/** 32 zero bytes: the `prev` of the first batch and of the first day. */
export const GENESIS: Uint8Array = new Uint8Array(HASH_SIZE);

const LEAF_PREFIX = Uint8Array.of(0x00);
const NODE_PREFIX = Uint8Array.of(0x01);
const CHAIN_TAG = new TextEncoder().encode("cockpit-chain-v1");
const DAY_TAG = new TextEncoder().encode("cockpit-day-v1");
const U64_MAX = 2n ** 64n - 1n;
const EMPTY_ROOT = sha256(new Uint8Array(0));

// --- argument checks ----------------------------------------------------------------------------

function describe(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "object") return (value as object).constructor?.name ?? "object";
  return typeof value;
}

function requireBytes(value: unknown, what: string): Uint8Array {
  if (!(value instanceof Uint8Array)) throw new TypeError(`${what} must be a Uint8Array, got ${describe(value)}`);
  return value;
}

function requireHash(value: unknown, what: string): Uint8Array {
  const b = requireBytes(value, what);
  if (b.length !== HASH_SIZE) throw new RangeError(`${what} must be ${HASH_SIZE} bytes, got ${b.length}`);
  return b;
}

/** An exact integer as a bigint: a bigint, or an integer-valued number. */
function requireInt(value: unknown, what: string): bigint {
  if (typeof value === "bigint") return value;
  if (typeof value !== "number") throw new TypeError(`${what} must be an integer, got ${describe(value)}`);
  if (!Number.isInteger(value)) throw new RangeError(`${what} must be an integer, got ${value}`);
  return BigInt(value);
}

function requireByteItems(value: unknown, what: string): Uint8Array[] {
  if (!Array.isArray(value)) throw new TypeError(`${what} must be an array, got ${describe(value)}`);
  const out: Uint8Array[] = [];
  for (let i = 0; i < value.length; i++) out.push(requireBytes(value[i], `${what}[${i}]`)); // holes are undefined
  return out;
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

function be64(n: bigint): Uint8Array {
  const out = new Uint8Array(8);
  new DataView(out.buffer).setBigUint64(0, n);
  return out;
}

// --- hex ----------------------------------------------------------------------------------------

const HEX = /^(?:[0-9a-fA-F]{2})*$/;

/** Lowercase hex of `bytes`. */
export function toHex(bytes: Uint8Array): string {
  requireBytes(bytes, "bytes");
  let out = "";
  for (const b of bytes) out += b.toString(16).padStart(2, "0");
  return out;
}

/** Bytes of a hex string (even length, hex digits only, either case). */
export function fromHex(hex: string): Uint8Array {
  if (typeof hex !== "string") throw new TypeError(`hex must be a string, got ${describe(hex)}`);
  if (!HEX.test(hex)) throw new RangeError(`not an even-length hex string: ${JSON.stringify(hex)}`);
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(2 * i, 2 * i + 2), 16);
  return out;
}

// --- row hashes ---------------------------------------------------------------------------------

/** `sha256(salt || canonical)`; the salt must be exactly 16 bytes. */
export function rowHash(salt: Uint8Array, canonical: Uint8Array): Uint8Array {
  requireBytes(salt, "salt");
  requireBytes(canonical, "canonical");
  if (salt.length !== SALT_SIZE) throw new RangeError(`salt must be ${SALT_SIZE} bytes, got ${salt.length}`);
  return sha256(concat(salt, canonical));
}

// --- RFC 6962 Merkle tree -----------------------------------------------------------------------

const leafHash = (data: Uint8Array): Uint8Array => sha256(concat(LEAF_PREFIX, data));
const nodeHash = (left: Uint8Array, right: Uint8Array): Uint8Array => sha256(concat(NODE_PREFIX, left, right));

/** Largest power of two strictly less than n (n >= 2). */
function split(n: number): number {
  let k = 1;
  while (k * 2 < n) k *= 2;
  return k;
}

function mth(hashes: Uint8Array[], lo: number, hi: number): Uint8Array {
  const n = hi - lo;
  if (n === 1) return hashes[lo];
  const k = split(n);
  return nodeHash(mth(hashes, lo, lo + k), mth(hashes, lo + k, hi));
}

function path(m: number, hashes: Uint8Array[], lo: number, hi: number): Uint8Array[] {
  const n = hi - lo;
  if (n === 1) return [];
  const k = split(n);
  if (m < k) return [...path(m, hashes, lo, lo + k), mth(hashes, lo + k, hi)];
  return [...path(m - k, hashes, lo + k, hi), mth(hashes, lo, lo + k)];
}

/** RFC 6962 Merkle Tree Hash of raw leaf data, in order. The empty tree's root is `sha256("")`. */
export function merkleRoot(leaves: Uint8Array[]): Uint8Array {
  const items = requireByteItems(leaves, "leaves");
  if (items.length === 0) return EMPTY_ROOT.slice();
  return mth(items.map(leafHash), 0, items.length);
}

/** RFC 6962 audit path for `leaves[index]`, leaf to root. A single-leaf tree has an empty proof. */
export function inclusionProof(leaves: Uint8Array[], index: number): Uint8Array[] {
  const items = requireByteItems(leaves, "leaves");
  const i = requireInt(index, "index");
  if (items.length === 0) throw new RangeError("cannot prove inclusion in an empty tree");
  if (i < 0n || i >= BigInt(items.length)) {
    throw new RangeError(`index ${i} out of range for ${items.length} leaves`);
  }
  return path(Number(i), items.map(leafHash), 0, items.length);
}

function equal(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

/**
 * Whether raw leaf data `leaf` sits at `index` in a tree of `treeSize` leaves with `root` (RFC 9162
 * section 2.1.3.2).
 *
 * Returns false, never throws, for any proof that does not verify: a tampered, reordered, short, long
 * or wrong-size proof element, the wrong leaf or root, a negative index, `index >= treeSize`, or a zero
 * or negative `treeSize`. The root alone does not commit to `treeSize` (index 2 verifies in trees of 5
 * and 6 leaves); bind the size separately, as `chainRoot` does with `nRows`.
 *
 * Throws only for arguments of the wrong type (TypeError) or a root that is not 32 bytes or a
 * non-integer index or size (RangeError).
 */
export function verifyInclusion(
  leaf: Uint8Array,
  index: number | bigint,
  treeSize: number | bigint,
  proof: Uint8Array[],
  root: Uint8Array,
): boolean {
  requireBytes(leaf, "leaf");
  const i = requireInt(index, "index");
  const size = requireInt(treeSize, "treeSize");
  const elements = requireByteItems(proof, "proof");
  requireHash(root, "root");

  if (i < 0n || i >= size) return false;
  let fn = i;
  let sn = size - 1n;
  let r = leafHash(leaf);
  for (const p of elements) {
    if (p.length !== HASH_SIZE || sn === 0n) return false;
    if ((fn & 1n) === 1n || fn === sn) {
      r = nodeHash(p, r);
      while (fn !== 0n && (fn & 1n) === 0n) {
        fn >>= 1n;
        sn >>= 1n;
      }
    } else {
      r = nodeHash(r, p);
    }
    fn >>= 1n;
    sn >>= 1n;
  }
  return sn === 0n && equal(r, root);
}

// --- chained batch roots and day roots ----------------------------------------------------------

/** `sha256("cockpit-chain-v1" || prev || batchRoot || nRows as 8-byte big-endian)`; nRows in [0, 2**64). */
export function chainRoot(prev: Uint8Array, batchRoot: Uint8Array, nRows: number | bigint): Uint8Array {
  requireHash(prev, "prev");
  requireHash(batchRoot, "batchRoot");
  const n = requireInt(nRows, "nRows");
  if (n < 0n || n > U64_MAX) throw new RangeError(`nRows must be in [0, 2**64), got ${n}`);
  return sha256(concat(CHAIN_TAG, prev, batchRoot, be64(n)));
}

/**
 * `sha256("cockpit-day-v1" || prevDay || merkleRoot(chainedRoots) || count as 8-byte big-endian)`.
 *
 * `chainedRoots` is taken exactly as given (callers sort by model version, then batch sequence).
 * A day with no batches still has a root.
 */
export function dayRoot(prevDay: Uint8Array, chainedRoots: Uint8Array[]): Uint8Array {
  requireHash(prevDay, "prevDay");
  const roots = requireByteItems(chainedRoots, "chainedRoots");
  roots.forEach((r, i) => requireHash(r, `chainedRoots[${i}]`));
  return sha256(concat(DAY_TAG, prevDay, merkleRoot(roots), be64(BigInt(roots.length))));
}
