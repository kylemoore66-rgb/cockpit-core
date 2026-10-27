import { readFileSync } from "node:fs";

// Shared fixtures: the same file the Python suite loads.
export const cases = JSON.parse(
  readFileSync(new URL("../../fixtures/cases.json", import.meta.url), "utf-8"),
);
