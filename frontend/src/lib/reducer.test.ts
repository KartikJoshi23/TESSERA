import { describe, expect, it } from "vitest";
import { type CaseEvent, parseEvent } from "./events";
import { emptyView, fold, reduce } from "./reducer";
import recorded from "./__fixtures__/worked-case.json";

const events = recorded.events as CaseEvent[];

function event(type: string, payload: Record<string, unknown>, actor = "ORC", seq = 1): CaseEvent {
  return { seq, case_id: "c", ts: "2026-11-05T00:00:00Z", actor, type, payload };
}

describe("a recorded case", () => {
  const view = fold(events);

  it("reaches the result the backend reached", () => {
    expect(view.final?.result).toBe("CONFLICTS");
    expect(view.final?.hardConflicts).toEqual(["HC1", "HC4", "HC5"]);
    expect(view.ended).toBe("finished");
  });

  it("shows the veto and the second proposal", () => {
    expect(view.verdicts.map((verdict) => verdict.decision)).toEqual(["VETO", "APPROVE"]);
    expect(view.verdicts[0]?.gates.filter((gate) => !gate.passed).map((gate) => gate.gate)).toEqual([
      "G5",
    ]);
    expect(view.proposals).toHaveLength(2);
  });

  it("follows the rounds in order and marks what happened in them", () => {
    expect(view.rounds.map((round) => round.phase)).toEqual([
      "R0",
      "R1",
      "R2",
      "reconcile",
      "synthesis",
      "verify",
      "remediate",
      "verify",
    ]);
    expect(view.rounds.map((round) => round.flag)).toEqual([
      null,
      null,
      "conflict",
      null,
      null,
      "veto",
      null,
      "approve",
    ]);
  });

  it("carries a challenge through to the revision", () => {
    const vara = view.findings.find(
      (finding) => finding.author === "JUR" && finding.assertion.regulator === "VARA",
    );
    expect(vara?.version).toBe(2);
    expect(vara?.assertion.status).toBe("possible");
    expect(view.agents.JUR.challenged).toBe(false);
    expect(view.agents.JUR.version).toBe(2);
    expect(view.messages.map((message) => message.performative)).toContain("CHALLENGE");
  });

  it("closes every conflict with the rule that settled it", () => {
    expect(view.conflicts.every((conflict) => conflict.status === "resolved")).toBe(true);
    expect(new Set(view.conflicts.map((conflict) => conflict.rule))).toEqual(new Set(["P2", "P3"]));
  });

  it("remembers which findings the result rests on", () => {
    expect(view.final?.findingIds.length).toBeGreaterThan(3);
    const known = new Set(view.findings.map((finding) => finding.id));
    expect(view.final?.findingIds.every((id) => known.has(id))).toBe(true);
  });

  it("leaves no agent working once the case has finished", () => {
    const statuses = Object.values(view.agents).map((agent) => agent.status);
    expect(statuses).not.toContain("thinking");
    expect(statuses).not.toContain("tool");
  });

  it("states what the policy derived, apart from what was proposed", () => {
    expect(view.policy?.result).toBe("CONFLICTS");
    expect(Object.keys(view.policy?.hardConflicts ?? {})).toEqual(["HC1", "HC4", "HC5"]);
  });

  it("counts what the case cost", () => {
    expect(view.requests).toBe(recorded.telemetry_requests);
    expect(view.toolCalls).toBeGreaterThan(5);
    expect(view.evidence).toBeGreaterThan(5);
  });

  it("is the same picture whether it is folded or built up one event at a time", () => {
    let stepped = emptyView();
    for (const item of events) stepped = reduce(stepped, item);
    expect(stepped).toEqual(view);
  });

  it("holds no restricted value, because the stored events hold none", () => {
    const text = JSON.stringify(view);
    expect(text).not.toContain("Lumen Crest");
    expect(text).not.toContain("Gate Village");
    expect(text).toContain("⟦R:");
  });
});

describe("single events", () => {
  it("ignores an event type it does not know", () => {
    const view = reduce(emptyView(), event("something.new", {}));
    expect({ ...view, lastSeq: 0 }).toEqual(emptyView());
  });

  it("does not change the view it was given", () => {
    const before = emptyView();
    const copy = structuredClone(before);
    reduce(before, event("agent.activated", {}, "JUR"));
    expect(before).toEqual(copy);
  });

  it("marks a failed agent and says so", () => {
    const view = reduce(emptyView(), event("agent.failed", { code: "model_error" }, "CMA"));
    expect(view.agents.CMA.status).toBe("failed");
    expect(view.announcement).toContain("CMA");
  });

  it("announces a veto with its reason", () => {
    const view = reduce(
      emptyView(),
      event("verifier.decision", {
        proposal_version: 1,
        decision: "VETO",
        gates: [{ gate: "G5", passed: false }],
        veto_reasons: ["G5: banned wording: clone"],
      }),
    );
    expect(view.announcement).toContain("G5");
  });

  it("marks a case nothing is running", () => {
    expect(reduce(emptyView(), event("case.interrupted", {})).ended).toBe("interrupted");
  });

  it("tracks the single agent like any other", () => {
    const view = reduce(emptyView(), event("agent.activated", {}, "SA"));
    expect(view.agents.SA.status).toBe("thinking");
    expect(view.agents.JUR.status).toBe("idle");
  });

  it("ends an agent's turn when the case moves to the next round", () => {
    const working = reduce(emptyView(), event("agent.activated", {}, "VER"));
    const next = reduce(working, event("round.started", { phase: "remediate" }));
    expect(next.agents.VER.status).toBe("done");
  });

  it("leaves a failed agent marked as failed when the case moves on", () => {
    const failed = reduce(emptyView(), event("agent.failed", {}, "CMA"));
    const next = reduce(failed, event("round.started", { phase: "R2" }));
    expect(next.agents.CMA.status).toBe("failed");
  });

  it("names the record a tool read", () => {
    const view = reduce(
      emptyView(),
      event(
        "tool.called",
        { tool: "cma_register_lookup", summary: { source_id: "cma", snapshot_date: "2026-11-04" } },
        "CMA",
      ),
    );
    expect(view.agents.CMA.tool).toBe("cma_register_lookup");
    expect(view.agents.CMA.source).toBe("cma · 2026-11-04");
  });

  it("clears a challenge once it has an answer, and only then", () => {
    const posted = reduce(
      emptyView(),
      event("finding.posted", { finding_id: "F-1", author: "JUR", assertion: {} }, "JUR"),
    );
    const challenge = {
      msg_id: "M-1",
      sender: "VARA",
      recipients: ["JUR"],
      performative: "CHALLENGE",
      refs: ["F-1"],
    };
    const challenged = reduce(posted, event("message.sent", challenge, "VARA"));
    expect(challenged.agents.JUR.challenged).toBe(true);
    expect(challenged.findings[0]?.status).toBe("challenged");

    const rebuttal = {
      msg_id: "M-2",
      sender: "JUR",
      recipients: ["VARA"],
      performative: "REBUT",
      refs: ["F-1"],
      in_reply_to: "M-1",
    };
    const answered = reduce(challenged, event("message.sent", rebuttal, "JUR"));
    expect(answered.agents.JUR.challenged).toBe(false);
    // As on the blackboard, a rebuttal answers the challenge but the finding stays challenged.
    expect(answered.findings[0]?.status).toBe("challenged");
  });

  it("leaves a withdrawn finding as it is when an agent's findings are superseded", () => {
    const posted = reduce(
      reduce(
        emptyView(),
        event("finding.posted", { finding_id: "F-1", author: "SA", assertion: {} }, "SA"),
      ),
      event("finding.posted", { finding_id: "F-2", author: "SA", assertion: {} }, "SA"),
    );
    const conceded = reduce(
      posted,
      event(
        "message.sent",
        { msg_id: "M-1", sender: "SA", performative: "CONCEDE", refs: ["F-1"] },
        "SA",
      ),
    );
    const view = reduce(conceded, event("findings.superseded", { author: "SA" }));
    expect(view.findings.map((finding) => finding.status)).toEqual(["withdrawn", "superseded"]);
  });

  it("keeps the vote behind a sampled result", () => {
    const view = reduce(
      emptyView(),
      event("votes.counted", { votes: { UNVERIFIED: 3, CONFLICTS: 2 } }),
    );
    expect(view.votes).toEqual({ UNVERIFIED: 3, CONFLICTS: 2 });
  });

  it("marks a conceded finding as withdrawn", () => {
    const posted = reduce(
      emptyView(),
      event("finding.posted", { finding_id: "F-1", author: "JUR", assertion: {} }, "JUR"),
    );
    const view = reduce(
      posted,
      event(
        "message.sent",
        { msg_id: "M-2", sender: "JUR", performative: "CONCEDE", refs: ["F-1"] },
        "JUR",
      ),
    );
    expect(view.findings[0]?.status).toBe("withdrawn");
  });
});

describe("parsing", () => {
  it("accepts a stored event", () => {
    const parsed = parseEvent(JSON.stringify(events[0]));
    expect(parsed?.type).toBe("case.created");
  });

  it("turns the server's note about a stopped case into an event", () => {
    const parsed = parseEvent(JSON.stringify({ case_id: "c", type: "case.interrupted" }));
    expect(parsed?.type).toBe("case.interrupted");
  });

  it("refuses anything else", () => {
    expect(parseEvent(JSON.stringify({ nonsense: true }))).toBeNull();
  });

  it("refuses text that is not JSON, without throwing", () => {
    expect(parseEvent("{not json")).toBeNull();
    expect(parseEvent("null")).toBeNull();
  });
});
