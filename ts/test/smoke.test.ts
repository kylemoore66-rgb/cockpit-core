import { expect, test } from "vitest";
import { VERSION } from "../src/index.js";
import { cases } from "./cases.js";

test("fixture loads", () => {
  expect(cases.settlement[0].profit).toBe("90.91");
});

test("VERSION is 0.2.0", () => {
  expect(VERSION).toBe("0.2.0");
});
