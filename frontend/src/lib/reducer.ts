/**
 * The one place events become what the screen shows. It is a pure function, so live streaming and
 * replay draw exactly the same picture, and a recorded case can be tested without a browser.
 *
 * It mirrors the blackboard's own replay (`backend/src/tessera/blackboard/board.py`): a finding's
 * status changes for the same events, and for no others.
 */
import type { CaseEvent } from "./events";

export const AGENTS = ["JUR", "CMA", "DFSA", "VARA", "CLN", "REC", "VER", "SA"] as const;
export type AgentKey = (typeof AGENTS)[number];
export type AgentStatus = "idle" | "thinking" | "tool" | "done" | "failed";

export interface AgentState {
  status: AgentStatus;
  /** A challenge to one of this agent's findings has not been answered yet. */
  challenged: boolean;
  version: number;
  requests: number;
  tokens: number;
  tool: string | null;
  /** The record the latest tool read, such as "cma_licensed · 2026-11-04". */
  source: string | null;
  reasoning: string;
}

export interface Finding {
  id: string;
  author: string;
  type: string;
  assertion: Record<string, unknown>;
  version: number;
  status: string;
  confidence: string;
  evidenceIds: string[];
  unknownEvidence: number;
  rationale: string;
  seq: number;
}

export interface Message {
  id: string;
  sender: string;
  recipients: string[];
  performative: string;
  refs: string[];
  body: Record<string, unknown>;
  rationale: string;
  inReplyTo: string | null;
  evidenceIds: string[];
  ruleIds: string[];
  seq: number;
}

export interface Conflict {
  id: string;
  type: string;
  findingIds: string[];
  detectedBy: string;
  summary: string;
  status: string;
  rule: string | null;
  outcome: string | null;
  rationale: string;
}

export interface Round {
  phase: string;
  seq: number;
  flag: "conflict" | "veto" | "approve" | null;
}

export interface Proposal {
  version: number;
  result: string;
  explanation: string;
  hardConflicts: string[];
  reasons: string[];
  findingIds: string[];
}

export interface Gate {
  gate: string;
  passed: boolean;
  detail: string;
}

export interface Contradiction {
  evidenceId: string;
  rationale: string;
}

export interface Verdict {
  version: number;
  decision: string;
  gates: Gate[];
  reasons: string[];
  /** What the Verifier's own reading found, apart from the fixed gates. */
  contradictions: Contradiction[];
  underCall: boolean;
}

export interface PolicyView {
  result: string;
  hardConflicts: Record<string, string[]>;
  reasons: string[];
}

export interface FinalResult {
  result: string;
  wording: string;
  explanation: string;
  hardConflicts: string[];
  reasons: string[];
  policyResult: string | null;
  findingIds: string[];
  disclaimer: string;
}

export interface ContactPoint {
  id: string;
  kind: string;
  raw: string;
  role: string;
}

export interface CaseView {
  caseId: string | null;
  condition: string | null;
  mode: string | null;
  model: string | null;
  offer: string | null;
  contacts: ContactPoint[];
  agents: Record<AgentKey, AgentState>;
  /** The agent that acted last. Presenter mode follows it. */
  active: AgentKey | null;
  findings: Finding[];
  messages: Message[];
  conflicts: Conflict[];
  rounds: Round[];
  proposals: Proposal[];
  verdicts: Verdict[];
  policy: PolicyView | null;
  final: FinalResult | null;
  evidence: number;
  requests: number;
  tokens: number;
  toolCalls: number;
  repairs: number;
  rejected: number;
  ended: "finished" | "aborted" | "interrupted" | null;
  lastSeq: number;
  /** What just happened, in a sentence, for the screen-reader announcement. */
  announcement: string;
}

function freshAgent(): AgentState {
  return {
    status: "idle",
    challenged: false,
    version: 1,
    requests: 0,
    tokens: 0,
    tool: null,
    source: null,
    reasoning: "",
  };
}

export function emptyView(): CaseView {
  return {
    caseId: null,
    condition: null,
    mode: null,
    model: null,
    offer: null,
    contacts: [],
    agents: Object.fromEntries(AGENTS.map((key) => [key, freshAgent()])) as Record<
      AgentKey,
      AgentState
    >,
    active: null,
    findings: [],
    messages: [],
    conflicts: [],
    rounds: [],
    proposals: [],
    verdicts: [],
    policy: null,
    final: null,
    evidence: 0,
    requests: 0,
    tokens: 0,
    toolCalls: 0,
    repairs: 0,
    rejected: 0,
    ended: null,
    lastSeq: 0,
    announcement: "",
  };
}

export const isAgent = (key: string): key is AgentKey =>
  (AGENTS as readonly string[]).includes(key);

const AGENT_NAMES: Record<string, string> = {
  JUR: "Jurisdiction",
  CLN: "Contact check",
  REC: "Reconciler",
  VER: "Verifier",
  SA: "Single agent",
};

const agentName = (key: string): string => AGENT_NAMES[key] ?? key;

function withAgent(view: CaseView, key: string, change: Partial<AgentState>): CaseView {
  if (!isAgent(key)) return view;
  return { ...view, agents: { ...view.agents, [key]: { ...view.agents[key], ...change } } };
}

/** Every agent that was still working has finished, because the work has moved on. */
function settleAgents(view: CaseView): CaseView {
  const agents = { ...view.agents };
  for (const key of AGENTS) {
    const agent = agents[key];
    if (agent.status === "thinking" || agent.status === "tool") {
      agents[key] = { ...agent, status: "done", tool: null };
    }
  }
  return { ...view, agents };
}

function toFinding(payload: Record<string, unknown>, seq: number): Finding {
  const assertion = (payload.assertion ?? {}) as Record<string, unknown>;
  return {
    id: String(payload.finding_id),
    author: String(payload.author),
    type: String(assertion.type ?? ""),
    assertion,
    version: Number(payload.version ?? 1),
    status: String(payload.status ?? "active"),
    confidence: String(payload.confidence ?? ""),
    evidenceIds: (payload.evidence_ids ?? []) as string[],
    unknownEvidence: ((payload.unknown_evidence_ids ?? []) as string[]).length,
    rationale: String(payload.rationale ?? ""),
    seq,
  };
}

function flagLatestRound(view: CaseView, flag: Round["flag"]): CaseView {
  const rounds = [...view.rounds];
  const last = rounds.at(-1);
  if (last && (flag === "veto" || last.flag === null)) {
    rounds[rounds.length - 1] = { ...last, flag };
  }
  return { ...view, rounds };
}

/** Which agents have a challenge waiting for an answer. */
function markChallenged(view: CaseView): CaseView {
  const answered = new Set(view.messages.map((message) => message.inReplyTo));
  const waiting = new Set<string>();
  for (const message of view.messages) {
    if (message.performative !== "CHALLENGE" || answered.has(message.id)) continue;
    const target = view.findings.find((finding) => finding.id === message.refs[0]);
    if (target) waiting.add(target.author);
  }
  const agents = { ...view.agents };
  for (const key of AGENTS) {
    const challenged = waiting.has(key);
    if (agents[key].challenged !== challenged) agents[key] = { ...agents[key], challenged };
  }
  return { ...view, agents };
}

function setFindingStatus(view: CaseView, id: string | undefined, status: string): CaseView {
  return {
    ...view,
    findings: view.findings.map((finding) =>
      finding.id === id ? { ...finding, status } : finding,
    ),
  };
}

function onMessage(view: CaseView, payload: Record<string, unknown>, seq: number): CaseView {
  const message: Message = {
    id: String(payload.msg_id),
    sender: String(payload.sender),
    recipients: (payload.recipients ?? []) as string[],
    performative: String(payload.performative),
    refs: (payload.refs ?? []) as string[],
    body: (payload.body ?? {}) as Record<string, unknown>,
    rationale: String(payload.rationale ?? ""),
    inReplyTo: (payload.in_reply_to ?? null) as string | null,
    evidenceIds: (payload.evidence_ids ?? []) as string[],
    ruleIds: (payload.rule_ids ?? []) as string[],
    seq,
  };
  // A message closes the sender's turn, even one that posted no findings.
  let next = withAgent({ ...view, messages: [...view.messages, message] }, message.sender, {
    status: "done",
    tool: null,
  });
  if (message.performative === "CHALLENGE") {
    next = setFindingStatus(next, message.refs[0], "challenged");
  } else if (message.performative === "CONCEDE") {
    next = setFindingStatus(next, message.refs[0], "withdrawn");
  }
  return markChallenged(next);
}

function apply(view: CaseView, event: CaseEvent): CaseView {
  const { payload, actor, type } = event;
  const seq = event.seq ?? view.lastSeq + 1;
  switch (type) {
    case "case.created":
      return {
        ...view,
        caseId: String(payload.case_id),
        condition: String(payload.condition),
        mode: String(payload.mode ?? ""),
        offer: String(payload.offer_text),
        model: String((payload.config as { model?: string } | undefined)?.model ?? ""),
        contacts: ((payload.contact_points ?? []) as Record<string, string>[]).map((point) => ({
          id: String(point.cp_id),
          kind: String(point.kind),
          raw: String(point.raw),
          role: String(point.role),
        })),
      };
    case "round.started":
      return {
        ...settleAgents(view),
        rounds: [...view.rounds, { phase: String(payload.phase), seq, flag: null }],
      };
    case "agent.activated":
      return {
        ...withAgent(view, actor, { status: "thinking", tool: null }),
        active: isAgent(actor) ? actor : view.active,
      };
    case "llm.response": {
      const tokens = event.usage?.total_tokens ?? 0;
      const agent = isAgent(actor) ? view.agents[actor] : null;
      const next = withAgent(view, actor, {
        status: "thinking",
        requests: (agent?.requests ?? 0) + 1,
        tokens: (agent?.tokens ?? 0) + tokens,
        reasoning: String(payload.reasoning ?? ""),
        tool: null,
      });
      return { ...next, requests: view.requests + 1, tokens: view.tokens + tokens };
    }
    case "tool.called": {
      const summary = (payload.summary ?? {}) as Record<string, unknown>;
      const source = summary.source_id
        ? [summary.source_id, summary.snapshot_date].filter(Boolean).join(" · ")
        : null;
      return {
        ...withAgent(view, actor, { status: "tool", tool: String(payload.tool), source }),
        toolCalls: view.toolCalls + 1,
      };
    }
    case "agent.repair":
      return { ...view, repairs: view.repairs + 1 };
    case "protocol.rejected":
      return { ...view, rejected: view.rejected + 1 };
    case "agent.failed":
      return {
        ...withAgent(view, actor, { status: "failed", tool: null }),
        announcement: `${agentName(actor)} could not finish its turn.`,
      };
    case "evidence.minted":
      return { ...view, evidence: view.evidence + 1 };
    case "finding.posted":
      return withAgent({ ...view, findings: [...view.findings, toFinding(payload, seq)] }, actor, {
        status: "done",
        tool: null,
      });
    case "finding.revised": {
      const revised = toFinding(payload, seq);
      return {
        ...withAgent(view, revised.author, { version: revised.version, status: "done" }),
        findings: view.findings.map((finding) => (finding.id === revised.id ? revised : finding)),
        announcement: `${agentName(revised.author)} revised finding ${revised.id}.`,
      };
    }
    case "findings.superseded":
      return {
        ...view,
        findings: view.findings.map((finding) =>
          finding.author === payload.author ? { ...finding, status: "superseded" } : finding,
        ),
      };
    case "message.sent":
      return onMessage(view, payload, seq);
    case "conflict.detected": {
      const conflict: Conflict = {
        id: String(payload.conflict_id),
        type: String(payload.type),
        findingIds: (payload.finding_ids ?? []) as string[],
        detectedBy: String(payload.detected_by),
        summary: String(payload.summary ?? ""),
        status: "open",
        rule: null,
        outcome: null,
        rationale: "",
      };
      return {
        ...flagLatestRound({ ...view, conflicts: [...view.conflicts, conflict] }, "conflict"),
        announcement: `Conflict ${conflict.type} opened: ${conflict.summary}`,
      };
    }
    case "conflict.resolved":
      return {
        ...view,
        conflicts: view.conflicts.map((conflict) =>
          conflict.id === payload.conflict_id
            ? {
                ...conflict,
                status: payload.outcome === "unresolved" ? "unresolved" : "resolved",
                rule: String(payload.precedence_rule),
                outcome: String(payload.outcome),
                rationale: String(payload.rationale ?? ""),
              }
            : conflict,
        ),
      };
    case "conflict.settled":
      return {
        ...view,
        conflicts: view.conflicts.map((conflict) =>
          conflict.id === payload.conflict_id ? { ...conflict, status: "settled" } : conflict,
        ),
      };
    case "proposal.created": {
      const claims = (payload.claims ?? []) as { finding_id?: string }[];
      return {
        ...withAgent(view, actor, { status: "done" }),
        proposals: [
          ...view.proposals,
          {
            version: Number(payload.version),
            result: String(payload.result),
            explanation: String(payload.explanation),
            hardConflicts: (payload.hard_conflicts ?? []) as string[],
            reasons: (payload.unverified_reasons ?? []) as string[],
            findingIds: claims.map((claim) => String(claim.finding_id)),
          },
        ],
      };
    }
    case "policy.derived":
      return {
        ...view,
        policy: {
          result: String(payload.result),
          hardConflicts: (payload.hard_conflicts ?? {}) as Record<string, string[]>,
          reasons: (payload.unverified_reasons ?? []) as string[],
        },
      };
    case "verifier.decision": {
      const decision = String(payload.decision);
      const reasons = (payload.veto_reasons ?? []) as string[];
      const verdict: Verdict = {
        version: Number(payload.proposal_version),
        decision,
        gates: (payload.gates ?? []) as Gate[],
        reasons,
        contradictions: ((payload.contradictions ?? []) as Record<string, string>[]).map(
          (item) => ({
            evidenceId: String(item.evidence_id),
            rationale: String(item.rationale ?? ""),
          }),
        ),
        underCall: Boolean(payload.under_call),
      };
      return {
        ...flagLatestRound(
          {
            ...withAgent(view, "VER", { status: "done" }),
            verdicts: [...view.verdicts, verdict],
          },
          decision === "VETO" ? "veto" : "approve",
        ),
        announcement:
          decision === "VETO"
            ? `Verifier vetoed the proposal: ${reasons[0] ?? "see the report"}`
            : "Verifier approved the proposal.",
      };
    }
    case "result.finalized": {
      const detail = (payload.detail ?? {}) as { policy_result?: string };
      const claims = (payload.claims ?? []) as { finding_id?: string }[];
      const wording = String(payload.wording);
      return {
        ...settleAgents(view),
        ended: "finished",
        final: {
          result: String(payload.result),
          wording,
          explanation: String(payload.explanation),
          hardConflicts: (payload.hard_conflicts ?? []) as string[],
          reasons: (payload.unverified_reasons ?? []) as string[],
          policyResult: detail.policy_result ?? null,
          findingIds: claims.map((claim) => String(claim.finding_id)),
          disclaimer: String(payload.disclaimer ?? ""),
        },
        announcement: `Result: ${wording}.`,
      };
    }
    case "case.aborted":
      return {
        ...settleAgents(view),
        ended: "aborted",
        announcement: "The case stopped with an error.",
      };
    case "case.interrupted":
      return {
        ...settleAgents(view),
        ended: "interrupted",
        announcement: "This case did not finish.",
      };
    default:
      return view;
  }
}

export function reduce(view: CaseView, event: CaseEvent): CaseView {
  return { ...apply(view, event), lastSeq: event.seq ?? view.lastSeq };
}

export function fold(events: readonly CaseEvent[]): CaseView {
  return events.reduce(reduce, emptyView());
}
