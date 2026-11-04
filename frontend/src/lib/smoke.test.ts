import { describe, expect, it } from "vitest";
import { summarize } from "./smoke";

const item = (gold: string, result: string, requests = 1) => ({
  case: "S01",
  gold,
  result,
  requests,
  tokens: 10,
  seconds: 2,
});

describe("a smoke run's summary", () => {
  const row = summarize({
    run: "crew",
    condition: "CREW-FULL",
    rate_limited: 0,
    cases: [
      item("CONSISTENT", "CONSISTENT"),
      item("CONFLICTS", "CONSISTENT"),
      item("UNVERIFIED", "CONSISTENT"),
      item("CONSISTENT", "UNVERIFIED"),
      item("CONFLICTS", "CONFLICTS", 4),
    ],
  });

  it("counts agreement with the hand labels", () => {
    expect(row.total).toBe(5);
    expect(row.agreed).toBe(2);
  });

  it("counts every false Consistent as false reassurance", () => {
    expect(row.falseReassurance).toBe(2);
  });

  it("keeps caution apart from false reassurance", () => {
    expect(row.overCautious).toBe(1);
  });

  it("adds up what the run spent", () => {
    expect(row.requests).toBe(8);
    expect(row.tokens).toBe(50);
    expect(row.seconds).toBe(10);
  });
});
