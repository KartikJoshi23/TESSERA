"use client";

import { ChevronRight, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Masked } from "@/components/Masked";
import type { CaseEvent } from "@/lib/events";
import type { AgentKey, CaseView, Conflict, Finding, Message, Verdict } from "@/lib/reducer";
import {
  type AgentLook,
  agentLook,
  CONFLICT_LABEL,
  describeAssertion,
  PERFORMATIVE_COLOR,
  resultLook,
} from "@/lib/vocabulary";
import { Glyph } from "./Glyph";

export type BoardTab = "findings" | "messages" | "conflicts" | "verifier" | "events";

const TABS: { id: BoardTab; label: string }[] = [
  { id: "findings", label: "Findings" },
  { id: "messages", label: "Messages" },
  { id: "conflicts", label: "Conflicts" },
  { id: "verifier", label: "Verifier" },
  { id: "events", label: "Events" },
];

const STATUS_STYLE: Record<string, string> = {
  challenged: "text-challenge border-challenge/50",
  withdrawn: "text-concede border-concede/50",
  superseded: "text-concede border-concede/50",
  open: "text-challenge border-challenge/50",
  resolved: "text-resolve border-resolve/40",
  settled: "text-concede border-concede/50",
  unresolved: "text-rebut border-rebut/50",
};

function Status({ status }: { status: string }) {
  return (
    <span
      className={`rounded border px-1 py-px text-[10px] leading-none whitespace-nowrap ${STATUS_STYLE[status] ?? "border-line text-text-3"}`}
    >
      {status}
    </span>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 text-xs leading-relaxed">
      <dt className="w-[4.5rem] shrink-0 text-text-3">{label}</dt>
      <dd className="min-w-0 break-words text-text-2">{children}</dd>
    </div>
  );
}

function Ids({ ids }: { ids: string[] }) {
  return (
    <span className="data flex flex-wrap gap-1">
      {ids.map((id) => (
        <span key={id} className="rounded bg-white/6 px-1 text-[10.5px]">
          {id}
        </span>
      ))}
    </span>
  );
}

interface RowProps {
  open: boolean;
  onToggle: () => void;
  summary: React.ReactNode;
  children: React.ReactNode;
  testId?: string;
}

/** One entry that opens to show its detail. Opening it in code also brings it into view. */
function Row({ open, onToggle, summary, children, testId }: RowProps) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (open) ref.current?.scrollIntoView({ block: "nearest" });
  }, [open]);
  return (
    <li ref={ref} className="lazy-row border-b border-line last:border-0" data-testid={testId}>
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full cursor-pointer items-start gap-2 px-3 py-2.5 text-left hover:bg-white/5"
      >
        <ChevronRight
          size={13}
          aria-hidden
          className={`mt-0.5 shrink-0 text-text-3 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="min-w-0 flex-1">{summary}</span>
      </button>
      {open && <dl className="flex flex-col gap-1 px-8 pb-3">{children}</dl>}
    </li>
  );
}

function FindingRow({
  finding,
  look,
  open,
  onToggle,
}: {
  finding: Finding;
  look: AgentLook;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <Row
      open={open}
      onToggle={onToggle}
      testId="finding-row"
      summary={
        <>
          <span className="flex items-center gap-1.5 text-[11px]">
            <span
              aria-hidden
              className="inline-block size-2 rotate-45 rounded-[2px]"
              style={{ background: look.color }}
            />
            <span className="data text-text-2">{finding.id}</span>
            <span className="text-text-3">{look.name}</span>
            <span className="ml-auto flex items-center gap-1">
              {finding.version > 1 && <span className="data text-revise">v{finding.version}</span>}
              {finding.status !== "active" && <Status status={finding.status} />}
            </span>
          </span>
          <span className="mt-0.5 block text-[13px] leading-snug text-text">
            <Masked text={describeAssertion(finding.assertion)} />
          </span>
        </>
      }
    >
      {finding.rationale && (
        <Detail label="Rationale">
          <Masked text={finding.rationale} />
        </Detail>
      )}
      <Detail label="Confidence">{finding.confidence || "not stated"}</Detail>
      <Detail label="Evidence">
        {finding.evidenceIds.length ? <Ids ids={finding.evidenceIds} /> : "None cited"}
      </Detail>
      {finding.unknownEvidence > 0 && (
        <Detail label="Rejected">{finding.unknownEvidence} evidence IDs no tool minted</Detail>
      )}
    </Row>
  );
}

function bodyLines(body: Record<string, unknown>): [string, string][] {
  return Object.entries(body)
    .filter(([, value]) => value !== null && value !== "" && !Array.isArray(value))
    .map(([key, value]) => [key.replaceAll("_", " "), String(value)]);
}

function MessageRow({
  message,
  nameOf,
  open,
  onToggle,
}: {
  message: Message;
  nameOf: (actor: string) => string;
  open: boolean;
  onToggle: () => void;
}) {
  const lines = bodyLines(message.body);
  return (
    <Row
      open={open}
      onToggle={onToggle}
      testId="message-row"
      summary={
        <>
          <span className="flex items-center gap-1.5 text-[11px]">
            <Glyph performative={message.performative} size={13} />
            <span
              className="data font-medium"
              style={{ color: PERFORMATIVE_COLOR[message.performative] }}
            >
              {message.performative}
            </span>
            <span className="data ml-auto text-text-3">{message.id}</span>
          </span>
          <span className="mt-0.5 block text-[13px] text-text">
            {nameOf(message.sender)}
            <span className="text-text-3"> to </span>
            {message.recipients.map(nameOf).join(", ")}
          </span>
        </>
      }
    >
      {lines.map(([key, value]) => (
        <Detail key={key} label={key}>
          <Masked text={value} />
        </Detail>
      ))}
      {message.rationale && (
        <Detail label="Rationale">
          <Masked text={message.rationale} />
        </Detail>
      )}
      {message.refs.length > 0 && (
        <Detail label="About">
          <Ids ids={message.refs} />
        </Detail>
      )}
      {message.evidenceIds.length > 0 && (
        <Detail label="Evidence">
          <Ids ids={message.evidenceIds} />
        </Detail>
      )}
      {message.ruleIds.length > 0 && (
        <Detail label="Rules">
          <Ids ids={message.ruleIds} />
        </Detail>
      )}
    </Row>
  );
}

function ConflictRow({
  conflict,
  open,
  onToggle,
}: {
  conflict: Conflict;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <Row
      open={open}
      onToggle={onToggle}
      testId="conflict-row"
      summary={
        <>
          <span className="flex items-center gap-1.5 text-[11px]">
            <span className="data text-challenge">{conflict.type}</span>
            <span className="text-text-3">{CONFLICT_LABEL[conflict.type]}</span>
            <span className="ml-auto">
              <Status status={conflict.status} />
            </span>
          </span>
          <span className="mt-0.5 block text-[13px] leading-snug text-text">
            <Masked text={conflict.summary} />
          </span>
        </>
      }
    >
      <Detail label="Found by">{conflict.detectedBy === "REC" ? "Reconciler" : "Detector"}</Detail>
      <Detail label="Findings">
        <Ids ids={conflict.findingIds} />
      </Detail>
      {conflict.rule && (
        <Detail label="Resolved">
          {conflict.outcome} under {conflict.rule}
        </Detail>
      )}
      {conflict.rationale && (
        <Detail label="Rationale">
          <Masked text={conflict.rationale} />
        </Detail>
      )}
    </Row>
  );
}

function VerdictCard({ verdict }: { verdict: Verdict }) {
  const vetoed = verdict.decision === "VETO";
  return (
    <li className="border-b border-line px-3 py-3 last:border-0" data-testid="verdict">
      <p className="flex items-center gap-2 text-sm">
        <Glyph performative={verdict.decision} size={15} />
        <span
          className="data font-medium"
          style={{ color: vetoed ? "var(--color-veto)" : "var(--color-approve)" }}
        >
          {verdict.decision}
        </span>
        <span className="text-text-3">proposal v{verdict.version}</span>
      </p>
      <ul className="mt-2 flex flex-wrap gap-1" aria-label="Gates">
        {verdict.gates.map((gate) => (
          <li
            key={gate.gate}
            title={gate.detail || undefined}
            className={`data rounded border px-1 text-[10.5px] ${
              gate.passed ? "border-ver/40 text-ver" : "border-veto/60 text-veto"
            }`}
          >
            {gate.gate} {gate.passed ? "passed" : "failed"}
          </li>
        ))}
      </ul>
      {verdict.underCall && (
        <p className="mt-2 text-xs leading-relaxed text-text-2">
          The proposal understated what the findings support.
        </p>
      )}
      {verdict.contradictions.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1.5">
          {verdict.contradictions.map((item) => (
            <li key={item.evidenceId} className="text-xs leading-relaxed text-text-2">
              <span className="data text-text-3">{item.evidenceId}</span>{" "}
              <Masked text={item.rationale} />
            </li>
          ))}
        </ul>
      )}
      {verdict.gates.some((gate) => !gate.passed) && (
        <ul className="mt-2 flex flex-col gap-1">
          {verdict.reasons.map((reason) => (
            <li key={reason} className="text-xs leading-relaxed text-text-2">
              <Masked text={reason} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function VerifierPanel({ view }: { view: CaseView }) {
  if (!view.policy && view.verdicts.length === 0) return <Empty>Nothing to verify yet.</Empty>;
  return (
    <>
      {view.policy && (
        <div className="border-b border-line px-3 py-3">
          <p className="eyebrow">Decision policy</p>
          <p className="mt-1 text-sm">{resultLook(view.policy.result)?.label}</p>
          <p className="data mt-1 text-[11px] text-text-3">
            {[...Object.keys(view.policy.hardConflicts), ...view.policy.reasons].join(" · ") ||
              "No hard conflicts"}
          </p>
        </div>
      )}
      <ul>
        {[...view.verdicts].reverse().map((verdict) => (
          <VerdictCard key={verdict.version} verdict={verdict} />
        ))}
      </ul>
    </>
  );
}

function EventRow({
  event,
  index,
  actor,
  open,
  onToggle,
}: {
  event: CaseEvent;
  index: number;
  actor: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <Row
      open={open}
      onToggle={onToggle}
      summary={
        <span className="flex items-center gap-2 text-[11.5px]">
          <span className="data w-7 text-right text-text-3">{index + 1}</span>
          <span className="data text-text">{event.type}</span>
          <span className="ml-auto truncate text-text-3">{actor}</span>
        </span>
      }
    >
      <pre className="data pane-scroll max-h-56 overflow-x-auto rounded-md bg-black/30 p-2 text-[10.5px] leading-relaxed whitespace-pre-wrap text-text-2">
        {JSON.stringify(event.payload, null, 1).slice(0, 4000)}
      </pre>
    </Row>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-8 text-center text-sm text-text-3">{children}</p>;
}

interface Props {
  view: CaseView;
  events: CaseEvent[];
  tab: BoardTab;
  onTab: (tab: BoardTab) => void;
  open: string | null;
  onOpen: (id: string | null) => void;
  agent: AgentKey | null;
  onClearAgent: () => void;
}

/**
 * Every finding, message and conflict in writing. Everything the stage shows can be reached and
 * read here with a keyboard or a screen reader.
 */
export function Blackboard({ view, events, tab, onTab, open, onOpen, agent, onClearAgent }: Props) {
  const [openEvent, setOpenEvent] = useState<number | null>(null);
  const toggle = (id: string) => onOpen(open === id ? null : id);
  const mine = (key: string) => !agent || key === agent;
  const findings = view.findings.filter((finding) => mine(finding.author));
  const messages = view.messages.filter(
    (message) => mine(message.sender) || message.recipients.some(mine),
  );
  const lookOf = (key: string) => agentLook(key, view.condition);
  const nameOf = (key: string) => lookOf(key).name;
  const look = agent ? lookOf(agent) : null;
  const state = agent ? view.agents[agent] : null;
  const counts: Record<BoardTab, number | null> = {
    findings: findings.length,
    messages: messages.length,
    conflicts: view.conflicts.length,
    verifier: null,
    events: null,
  };

  return (
    <section className="glass flex min-h-0 flex-col overflow-hidden" aria-label="Blackboard">
      <div role="tablist" aria-label="Blackboard" className="flex gap-0.5 border-b border-line p-1.5">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            role="tab"
            type="button"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls="board-panel"
            onClick={() => onTab(id)}
            className={`flex-1 cursor-pointer rounded-lg px-1 py-1.5 text-xs font-medium whitespace-nowrap ${
              tab === id ? "bg-white/10 text-text" : "text-text-3 hover:text-text"
            }`}
          >
            {label} {counts[id] !== null && <span className="data text-text-3">{counts[id]}</span>}
          </button>
        ))}
      </div>

      {look && state && (
        <div className="border-b border-line px-3 py-2.5">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-semibold" style={{ color: look.color }}>
              {look.name}
            </span>
            <span className="data text-xs text-text-3">
              {state.requests} req · {state.tokens.toLocaleString("en")} tok
            </span>
            <button
              type="button"
              aria-label="Show every agent"
              onClick={onClearAgent}
              className="icon-button ml-auto size-6!"
            >
              <X size={14} />
            </button>
          </div>
          <p className="mt-0.5 text-xs text-text-3">{look.role}</p>
          {state.reasoning && (
            <details className="mt-1 text-xs text-text-2">
              <summary className="cursor-pointer text-text-3">Latest reasoning</summary>
              <p className="pane-scroll mt-1 max-h-32 leading-relaxed">
                <Masked text={state.reasoning} />
              </p>
            </details>
          )}
        </div>
      )}

      <div
        id="board-panel"
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
        className="pane-scroll min-h-0 flex-1"
      >
        {tab === "findings" &&
          (findings.length ? (
            <ul>
              {[...findings].reverse().map((finding) => (
                <FindingRow
                  key={finding.id}
                  finding={finding}
                  look={lookOf(finding.author)}
                  open={open === finding.id}
                  onToggle={() => toggle(finding.id)}
                />
              ))}
            </ul>
          ) : (
            <Empty>No findings yet.</Empty>
          ))}
        {tab === "messages" &&
          (messages.length ? (
            <ul>
              {[...messages].reverse().map((message) => (
                <MessageRow
                  key={message.id}
                  message={message}
                  nameOf={nameOf}
                  open={open === message.id}
                  onToggle={() => toggle(message.id)}
                />
              ))}
            </ul>
          ) : (
            <Empty>No messages yet.</Empty>
          ))}
        {tab === "conflicts" &&
          (view.conflicts.length ? (
            <ul>
              {[...view.conflicts].reverse().map((conflict) => (
                <ConflictRow
                  key={conflict.id}
                  conflict={conflict}
                  open={open === conflict.id}
                  onToggle={() => toggle(conflict.id)}
                />
              ))}
            </ul>
          ) : (
            <Empty>No conflicts so far.</Empty>
          ))}
        {tab === "verifier" && <VerifierPanel view={view} />}
        {tab === "events" && (
          <ol>
            {events.map((event, index) => (
              <EventRow
                key={event.seq ?? index}
                event={event}
                index={index}
                actor={nameOf(event.actor)}
                open={openEvent === index}
                onToggle={() => setOpenEvent(openEvent === index ? null : index)}
              />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
