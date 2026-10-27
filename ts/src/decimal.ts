import { Decimal as BaseDecimal } from "decimal.js";

/**
 * The package's Decimal: decimal.js at precision 40, configured once here.
 *
 * Money functions never do arithmetic with it; they compute exactly with bigints and divide once (see
 * `_exact.ts`). It is what they return, and what callers may pass in (any decimal.js Decimal works).
 *
 * Serialise these values with `toFixed` (`toFixed(2)` for money), never `toString`: decimal.js switches
 * to exponent notation for large and small values (for example `1e+21`), which the Python package and the
 * canonical strings never produce.
 */
export const Decimal = BaseDecimal.clone({ precision: 40 });
export type Decimal = BaseDecimal;

/** A money, price or probability input: a decimal.js Decimal, or a plain decimal string like "5.5". */
export type DecimalInput = BaseDecimal | string;
