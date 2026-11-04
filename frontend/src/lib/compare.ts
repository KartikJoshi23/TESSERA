/** What the Arena compares. Both systems are measured the same way, from their event logs. */
import type { CaseEvent } from "./events";
import type { CaseView } from "./reducer";
import { describeAssertion } from "./vocabulary";

export interface Metrics {
  requests: number;
  tokens: number;
  toolCalls: number;
  seconds: number | null;
  findings: number;
  messages: number;
  conflicts: number;
  vetoes: number;
}

export function metricsOf(view: CaseView, events: readonly CaseEvent[]): Metrics {
  const first = events[0];
  const last = events.at(-1);
  const seconds =
    first && last && view.ended
      ? Math.round((Date.parse(last.ts) - Date.parse(first.ts)) / 1000)
      : null;
  return {
    requests: view.requests,
    tokens: view.tokens,
    toolCalls: view.toolCalls,
    seconds,
    findings: view.findings.length,
    messages: view.messages.length,
    conflicts: view.conflicts.length,
    vetoes: view.verdicts.filter((verdict) => verdict.decision === "VETO").length,
  };
}

/** What a claim says, apart from which piece of evidence each system happened to cite. */
function claimKey(assertion: Record<string, unknown>): string {
  const said = Object.entries(assertion)
    .filter(([key]) => !key.endsWith("evidence_id"))
    .sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify(said);
}

function claimsOf(view: CaseView): Map<string, string> {
  const claims = new Map<string, string>();
  for (const id of view.final?.findingIds ?? []) {
    const finding = view.findings.find((item) => item.id === id);
    if (finding) claims.set(claimKey(finding.assertion), describeAssertion(finding.assertion));
  }
  return claims;
}

export interface ClaimDifference {
  onlyA: string[];
  both: string[];
  onlyB: string[];
}

export function claimDifference(a: CaseView, b: CaseView): ClaimDifference {
  const left = claimsOf(a);
  const right = claimsOf(b);
  return {
    onlyA: [...left].filter(([key]) => !right.has(key)).map(([, text]) => text),
    both: [...left].filter(([key]) => right.has(key)).map(([, text]) => text),
    onlyB: [...right].filter(([key]) => !left.has(key)).map(([, text]) => text),
  };
}

/** Two finished runs of one offer, named by condition in a joined log (see `tessera-replay`). */
export function pairsIn(ids: readonly string[]): { name: string; a: string; b: string }[] {
  const pairs: { name: string; a: string; b: string }[] = [];
  for (const id of ids) {
    if (!id.endsWith("~CREW-FULL")) continue;
    const name = id.slice(0, -"~CREW-FULL".length);
    const other = `${name}~SA-BASE`;
    if (ids.includes(other)) pairs.push({ name, a: id, b: other });
  }
  return pairs;
}

export interface Step {
  key: string;
  kind: "request" | "tool" | "finding" | "verdict" | "result";
  title: string;
  detail: string;
}

/** A single agent has no crew to draw, so its work is one line, in order. */
export function stepsOf(events: readonly CaseEvent[]): Step[] {
  const steps: Step[] = [];
  let requests = 0;
  let findings = 0;
  events.forEach((event, index) => {
    const key = String(event.seq ?? index);
    if (event.type === "llm.response") {
      requests += 1;
      steps.push({
        key,
        kind: "request",
        title: `Model request ${requests}`,
        detail: `${(event.usage?.total_tokens ?? 0).toLocaleString("en")} tokens`,
      });
    } else if (event.type === "tool.called") {
      const summary = (event.payload.summary ?? {}) as Record<string, unknown>;
      steps.push({
        key,
        kind: "tool",
        title: String(event.payload.tool),
        detail: [summary.source_id, summary.snapshot_date].filter(Boolean).join(" · "),
      });
    } else if (event.type === "finding.posted") {
      findings += 1;
      const last = steps.at(-1);
      const title = `${findings} ${findings === 1 ? "finding" : "findings"}`;
      if (last?.kind === "finding") last.title = title;
      else steps.push({ key, kind: "finding", title, detail: "" });
    } else if (event.type === "verifier.decision") {
      steps.push({
        key,
        kind: "verdict",
        title: `Verifier: ${String(event.payload.decision)}`,
        detail: `proposal v${String(event.payload.proposal_version)}`,
      });
    } else if (event.type === "result.finalized") {
      steps.push({ key, kind: "result", title: "Result", detail: "" });
    }
  });
  return steps;
}
