/**
 * The event log, as the browser receives it. Every event is validated, so a change on the server
 * is counted and reported to the viewer, and does not quietly draw a wrong picture.
 */
import { z } from "zod";

export const eventSchema = z.object({
  seq: z.number().nullable().optional(),
  case_id: z.string(),
  ts: z.string(),
  actor: z.string(),
  type: z.string(),
  payload: z.record(z.string(), z.any()),
  usage: z.record(z.string(), z.number()).nullable().optional(),
  latency_ms: z.number().nullable().optional(),
});

export type CaseEvent = z.infer<typeof eventSchema>;

/** The last event a case can emit. A stream ends here. */
export const TERMINAL = new Set(["result.finalized", "case.aborted", "case.interrupted"]);

function fromJson(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

export function parseEvent(data: string): CaseEvent | null {
  const raw = fromJson(data);
  const parsed = eventSchema.safeParse(raw);
  if (parsed.success) return parsed.data;
  const record = (raw ?? {}) as { type?: string; case_id?: string };
  if (record.type === "case.interrupted" && record.case_id) {
    // The server's own note that nothing is running this case. It is not a stored event.
    return {
      case_id: record.case_id,
      ts: new Date().toISOString(),
      actor: "ORC",
      type: "case.interrupted",
      payload: {},
    };
  }
  return null;
}
