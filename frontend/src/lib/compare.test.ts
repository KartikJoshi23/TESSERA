import { describe, expect, it } from "vitest";
import recorded from "./__fixtures__/worked-case.json";
import { claimDifference, metricsOf, pairsIn, stepsOf } from "./compare";
import type { CaseEvent } from "./events";
import { emptyView, fold, reduce } from "./reducer";

const events = recorded.events as CaseEvent[];
const crew = fold(events);

function finished(findings: Record<string, unknown>[]) {
  let view = emptyView();
  findings.forEach((assertion, index) => {
    view = reduce(view, {
      case_id: "c",
      ts: "2026-11-05T00:00:00Z",
      actor: "SA",
      type: "finding.posted",
      payload: { finding_id: `F-${index}`, author: "SA", assertion },
    });
  });
  return reduce(view, {
    case_id: "c",
    ts: "2026-11-05T00:00:00Z",
    actor: "ORC",
    type: "result.finalized",
    payload: {
      result: "CONFLICTS",
      wording: "",
      explanation: "",
      claims: findings.map((_, index) => ({ finding_id: `F-${index}` })),
    },
  });
}

describe("the metrics", () => {
  it("count the same things the case reports", () => {
    const metrics = metricsOf(crew, events);
    expect(metrics.requests).toBe(recorded.telemetry_requests);
    expect(metrics.vetoes).toBe(1);
    expect(metrics.conflicts).toBe(3);
    expect(metrics.seconds).not.toBeNull();
  });

  it("give no time until a case has ended", () => {
    expect(metricsOf(emptyView(), []).seconds).toBeNull();
  });
});

describe("the claim comparison", () => {
  const scope = { type: "register_no_match", regulator: "CMA" };
  const alert = {
    type: "alert_hit",
    source_id: "x",
    alert_evidence_id: "E-1",
    about: "other",
    matched_on: "name",
  };

  it("separates what only one system said", () => {
    const difference = claimDifference(finished([scope, alert]), finished([scope]));
    expect(difference.both).toHaveLength(1);
    expect(difference.onlyA).toHaveLength(1);
    expect(difference.onlyB).toEqual([]);
  });

  it("does not count citing different evidence as a different claim", () => {
    const left = finished([alert]);
    const right = finished([{ ...alert, alert_evidence_id: "E-2" }]);
    const difference = claimDifference(left, right);
    expect(difference.both).toHaveLength(1);
    expect(difference.onlyA).toEqual([]);
  });

  it("compares a case with itself as all shared", () => {
    const difference = claimDifference(crew, crew);
    expect(difference.onlyA).toEqual([]);
    expect(difference.onlyB).toEqual([]);
    expect(difference.both.length).toBeGreaterThan(0);
  });
});

describe("pairs in a joined log", () => {
  it("offers a pair only where both systems ran", () => {
    const ids = ["S01~CREW-FULL", "S01~SA-BASE", "S02~CREW-FULL", "S03~SA-BASE"];
    expect(pairsIn(ids)).toEqual([{ name: "S01", a: "S01~CREW-FULL", b: "S01~SA-BASE" }]);
  });
});

describe("a single agent's line of work", () => {
  function step(type: string, payload: Record<string, unknown> = {}, seq = 1): CaseEvent {
    return { seq, case_id: "c", ts: "2026-11-05T00:00:00Z", actor: "SA", type, payload };
  }

  it("reads in order, with the record each tool read", () => {
    const steps = stepsOf([
      { ...step("llm.response"), usage: { total_tokens: 1200 } },
      step("tool.called", {
        tool: "cma_register_lookup",
        summary: { source_id: "cma_licensed", snapshot_date: "2026-11-04" },
      }),
      step("result.finalized"),
    ]);
    expect(steps.map((item) => item.kind)).toEqual(["request", "tool", "result"]);
    expect(steps[0]?.detail).toBe("1,200 tokens");
    expect(steps[1]?.detail).toBe("cma_licensed · 2026-11-04");
  });

  it("folds a run of findings into one step", () => {
    const steps = stepsOf([step("finding.posted"), step("finding.posted"), step("finding.posted")]);
    expect(steps).toHaveLength(1);
    expect(steps[0]?.title).toBe("3 findings");
  });

  it("ignores events that are not steps", () => {
    expect(stepsOf([step("evidence.minted")])).toEqual([]);
  });
});
