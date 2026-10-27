import { expect, test } from "vitest";
import { cases } from "./cases.js";

test("fixture loads", () => {
  expect(cases.settlement[0].profit).toBe("90.91");
});
