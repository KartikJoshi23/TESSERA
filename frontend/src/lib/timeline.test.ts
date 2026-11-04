import { describe, expect, it } from "vitest";
import recorded from "./__fixtures__/worked-case.json";
import type { CaseEvent } from "./events";
import { nextMark, replayDelay, timelineOf } from "./timeline";

const events = recorded.events as CaseEvent[];

function at(ts: string): CaseEvent {
  return { case_id: "c", ts, actor: "ORC", type: "x", payload: {} };
}

describe("the timeline of a recorded case", () => {
  const timeline = timelineOf(events);

  it("covers every event after the case opens, once", () => {
    const counted = timeline.rounds.reduce((sum, round) => sum + round.count, 0);
    expect(counted).toBe(events.length - (timeline.rounds[0]?.start ?? 0));
  });

  it("starts each round where its event is", () => {
    for (const round of timeline.rounds) {
      expect(events[round.start]?.type).toBe("round.started");
    }
  });

  it("marks the veto over the conflicts in a round, as the reducer does", () => {
    expect(timeline.rounds.map((round) => round.mark)).toEqual([
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

  it("gives a jump target that shows the event", () => {
    const veto = timeline.marks.find((mark) => mark.kind === "veto");
    expect(events[(veto?.index ?? 0) - 1]?.payload.decision).toBe("VETO");
  });

  it("jumps forward to conflicts and vetoes, and never to an approval", () => {
    const first = nextMark(timeline.marks, 0);
    expect(first?.kind).toBe("conflict");
    const veto = timeline.marks.find((mark) => mark.kind === "veto");
    expect(nextMark(timeline.marks, veto?.index ?? 0)).toBeNull();
  });
});

describe("replay timing", () => {
  it("shortens a long model call but keeps it visible", () => {
    expect(replayDelay(at("2026-11-04T00:00:00Z"), at("2026-11-04T00:01:00Z"))).toBe(700);
  });

  it("never runs events together", () => {
    expect(replayDelay(at("2026-11-04T00:00:00Z"), at("2026-11-04T00:00:00Z"))).toBe(30);
  });

  it("copes with an edge of the log", () => {
    expect(replayDelay(undefined, at("2026-11-04T00:00:00Z"))).toBe(30);
  });
});
