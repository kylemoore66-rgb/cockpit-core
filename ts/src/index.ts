export const VERSION = "0.1.0";

export { Decimal, type DecimalInput } from "./decimal.js";
export { americanFromDecimal, decimalFromAmerican, implied } from "./odds.js";
export { DEFAULT_STAKE_SETTINGS, type StakeSettings, edge, fullKelly, sizeStake } from "./kelly.js";
export { type Settlement, profit, settlement } from "./settle.js";
