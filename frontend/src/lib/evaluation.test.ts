import { describe, expect, it } from "vitest";
import {
  bounds,
  type LevelReport,
  groupsOf,
  orderedSystems,
  reach,
  shown,
  signed,
  type SystemReport,
} from "./evaluation";

function system(groups: string[] = []): SystemReport {
  return {
    by_group: Object.fromEntries(
      groups.map((name) => [name, { items: 1, accuracy: 1, false_reassurance: 0 }]),
    ),
  } as unknown as SystemReport;
}

function level(systems: Record<string, SystemReport>): LevelReport {
  return { systems } as unknown as LevelReport;
}

describe("the order of systems", () => {
  it("runs from no model to the full crew", () => {
    const report = level({ "CREW-FULL": system(), "SA-BASE": system(), "RULES-ONLY": system() });
    expect(orderedSystems(report).map(([name]) => name)).toEqual([
      "RULES-ONLY",
      "SA-BASE",
      "CREW-FULL",
    ]);
  });

  it("keeps a system it does not know, last", () => {
    const report = level({ NEW: system(), "SA-BASE": system() });
    expect(orderedSystems(report).at(-1)?.[0]).toBe("NEW");
  });
});

describe("factors", () => {
  it("are listed once each, in number order", () => {
    const report = level({ a: system(["F10", "F2"]), b: system(["F2", "F1"]) });
    expect(groupsOf(report)).toEqual(["F1", "F2", "F10"]);
  });
});

describe("the reach of an axis", () => {
  it("covers the widest interval, in round steps", () => {
    const comparisons = [{ name: "a", pairs: 1, ci_low: -0.12, ci_high: 0.03 }];
    expect(reach(comparisons)).toBeCloseTo(0.15);
  });

  it("is never so narrow that noise looks large", () => {
    expect(reach([{ name: "a", pairs: 1, ci_low: 0, ci_high: 0.001 }])).toBeCloseTo(0.05);
  });
});

describe("numbers", () => {
  it("show a gap where there is no value", () => {
    expect(shown(null)).toBe("–");
    expect(shown(0)).toBe("0.000");
  });

  it("show an interval in brackets", () => {
    expect(bounds([0.1, 0.25])).toBe("[0.10, 0.25]");
  });

  it("carry their sign", () => {
    expect(signed(0.25)).toBe("+0.250");
    expect(signed(-0.25)).toBe("−0.250");
    expect(signed(0)).toBe("0.000");
  });
});
