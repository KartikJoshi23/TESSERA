/**
 * The shape of a whole case, for the timeline. It reads every event, not only those shown so far,
 * so someone replaying a case can see where it goes and jump there.
 */
import type { CaseEvent } from "./events";

export type MarkKind = "conflict" | "veto" | "approve";

export interface TimelineRound {
  phase: string;
  /** Where this round starts: how many events come before it. */
  start: number;
  count: number;
  mark: MarkKind | null;
}

export interface TimelineMark {
  index: number;
  kind: MarkKind;
}

export interface Timeline {
  rounds: TimelineRound[];
  marks: TimelineMark[];
}

function markOf(event: CaseEvent): MarkKind | null {
  if (event.type === "conflict.detected") return "conflict";
  if (event.type === "verifier.decision") {
    return event.payload.decision === "VETO" ? "veto" : "approve";
  }
  return null;
}

export function timelineOf(events: readonly CaseEvent[]): Timeline {
  const rounds: TimelineRound[] = [];
  const marks: TimelineMark[] = [];
  events.forEach((event, index) => {
    if (event.type === "round.started") {
      const last = rounds.at(-1);
      if (last) last.count = index - last.start;
      rounds.push({ phase: String(event.payload.phase), start: index, count: 0, mark: null });
    }
    const kind = markOf(event);
    if (kind) {
      // The index is the position just after the event, so jumping there shows it.
      marks.push({ index: index + 1, kind });
      const round = rounds.at(-1);
      if (round && (kind === "veto" || round.mark === null)) round.mark = kind;
    }
  });
  const last = rounds.at(-1);
  if (last) last.count = events.length - last.start;
  return { rounds, marks };
}

/** The first conflict or veto after a position, for "jump to the next one". */
export function nextMark(marks: readonly TimelineMark[], position: number): TimelineMark | null {
  return marks.find((mark) => mark.index > position && mark.kind !== "approve") ?? null;
}

const REPLAY_FACTOR = 6;
const SHORTEST_MS = 30;
const LONGEST_MS = 700;

/** How long replay waits before the next event at 1×. Model calls take far too long to sit through. */
export function replayDelay(previous: CaseEvent | undefined, next: CaseEvent | undefined): number {
  if (!previous || !next) return SHORTEST_MS;
  const gap = (Date.parse(next.ts) - Date.parse(previous.ts)) / REPLAY_FACTOR;
  if (Number.isNaN(gap)) return SHORTEST_MS;
  return Math.min(Math.max(gap, SHORTEST_MS), LONGEST_MS);
}
