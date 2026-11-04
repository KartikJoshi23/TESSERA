"use client";

import { ArrowRight, Download } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState } from "react";
import { Masked } from "@/components/Masked";
import { Notice, SyntheticBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { saveJson } from "@/lib/download";
import { useCaseEvents, useFoldedView, usePlayback } from "@/lib/hooks";
import type { AgentKey, CaseView } from "@/lib/reducer";
import {
  conditionName,
  isCrew,
  PERFORMATIVE_COLOR,
  PHASE_LABEL,
  PHASE_NOTE,
  RESULT_LOOK,
} from "@/lib/vocabulary";
import { Blackboard, type BoardTab } from "./Blackboard";
import { Glyph } from "./Glyph";
import { Stage } from "./Stage";
import { Timeline } from "./Timeline";

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="data text-sm text-text">{value}</span>
      <span className="text-[11px] text-text-3">{label}</span>
    </div>
  );
}

function CaseHeader({ id, view }: { id: string; view: CaseView }) {
  const model = view.condition === "RULES-ONLY" ? "no model" : view.model?.split("/").at(-1);
  return (
    <header className="flex flex-wrap items-center gap-x-5 gap-y-2">
      <div className="min-w-0">
        <p className="eyebrow">Case</p>
        <h1 className="data truncate text-lg font-medium" title={id}>
          {id}
        </h1>
      </div>
      <SyntheticBadge />
      <div className="flex flex-col text-sm">
        <span className="font-medium">{conditionName(view.condition)}</span>
        {model && <span className="data text-[11px] text-text-3">{model}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <Metric label="requests" value={view.requests} />
        <Metric label="tokens" value={view.tokens.toLocaleString("en")} />
        <Metric label="tool calls" value={view.toolCalls} />
        <Metric label="evidence" value={view.evidence} />
      </div>
      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          className="button h-9!"
          onClick={() => void api.trace(id).then((trace) => saveJson(`${id}-trace.json`, trace))}
          title="The event log, masked as stored"
        >
          <Download size={15} aria-hidden /> Trace
        </button>
        {view.final && (
          <Link href={`/cases/${encodeURIComponent(id)}/result`} className="button button-primary h-9!">
            Open the result <ArrowRight size={15} aria-hidden />
          </Link>
        )}
      </div>
    </header>
  );
}

function Legend() {
  return (
    <ul
      className="absolute bottom-3 left-4 grid grid-cols-3 gap-x-3 gap-y-0.5 text-[10px] text-text-3"
      aria-label="Message types"
    >
      {Object.keys(PERFORMATIVE_COLOR).map((performative) => (
        <li key={performative} className="flex items-center gap-1">
          <Glyph performative={performative} size={11} />
          {performative}
        </li>
      ))}
    </ul>
  );
}

function PhaseCaption({ view }: { view: CaseView }) {
  const phase = view.rounds.at(-1)?.phase;
  const rules = view.condition === "RULES-ONLY";
  if (view.votes) {
    const tally = Object.entries(view.votes)
      .map(([result, count]) => `${RESULT_LOOK[result]?.label ?? result}: ${count}`)
      .join(". ");
    return (
      <div className="pointer-events-none absolute top-3 left-4 z-10 max-w-60" data-testid="phase-caption">
        <p className="eyebrow">Five samples voted</p>
        <p className="mt-1 text-xs leading-snug text-text-2">{tally}.</p>
      </div>
    );
  }
  if (!phase && !rules) return null;
  const title = rules ? "Rules only" : (phase && PHASE_LABEL[phase]) || phase;
  const note = rules
    ? PHASE_NOTE.rules_only
    : !isCrew(view.condition)
      ? PHASE_NOTE.single_agent
      : phase && PHASE_NOTE[phase];
  return (
    <div className="pointer-events-none absolute top-3 left-4 z-10 max-w-60" data-testid="phase-caption">
      <p className="eyebrow">{title}</p>
      {note && <p className="mt-1 text-xs leading-snug text-text-2">{note}</p>}
    </div>
  );
}

/** Live, replay and presenter are one view: only the cursor into the event log differs. */
export function Theater({ id, replay }: { id: string; replay: boolean }) {
  const { events, state, unreadable } = useCaseEvents(id);
  const ended = state === "ended";
  const playback = usePlayback(events, ended, replay);
  const view = useFoldedView(events, playback.position);
  const [presenter, setPresenter] = useState(false);
  const [tab, setTab] = useState<BoardTab>("findings");
  const [open, setOpen] = useState<string | null>(null);
  const [agent, setAgent] = useState<AgentKey | null>(null);

  if (state === "failed" && events.length === 0) {
    return (
      <div className="mx-auto max-w-xl py-16">
        <Notice title="This case could not be opened">
          There is no case <span className="data">{id}</span> in the event log the API has open, or
          the API is not running.{" "}
          <Link className="underline" href="/">
            Back to the console
          </Link>
        </Notice>
      </div>
    );
  }

  const selectFinding = (finding: string) => {
    setTab("findings");
    setAgent(null);
    setOpen(finding);
  };
  const selectMessage = (message: string) => {
    setTab("messages");
    setAgent(null);
    setOpen(message);
  };
  const selectAgent = (key: AgentKey) => setAgent((current) => (current === key ? null : key));
  const resultHref = `/cases/${encodeURIComponent(id)}/result`;

  return (
    <div className="mx-auto flex w-full max-w-[1680px] flex-col gap-3 px-4 pb-6 lg:px-6">
      <CaseHeader id={id} view={view} />

      {unreadable > 0 && (
        <Notice title="Some events could not be read" tone="caution">
          {unreadable} events from the API did not match what this interface expects, so this view
          may be incomplete.
        </Notice>
      )}

      {state === "reconnecting" && (
        <p className="text-sm text-challenge" role="status">
          The connection dropped. Trying again.
        </p>
      )}

      <details className="glass-thin group px-3 py-2 text-sm">
        <summary className="cursor-pointer text-text-2">
          The offer, as the models saw it
          {view.contacts.length > 0 && (
            <span className="ml-2 text-xs text-text-3">{view.contacts.length} contact points</span>
          )}
        </summary>
        {view.offer && (
          <p className="mt-2 leading-relaxed text-text" dir="auto">
            <Masked text={view.offer} />
          </p>
        )}
      </details>

      <div
        className={`grid gap-3 ${presenter ? "" : "xl:h-[calc(100dvh-20.5rem)] xl:min-h-[34rem] xl:grid-cols-[minmax(0,1fr)_23rem]"}`}
      >
        <section
          className="glass relative flex min-h-0 flex-col items-center justify-center overflow-hidden p-2"
          aria-label="Orchestration stage"
        >
          <PhaseCaption view={view} />
          <div className="relative aspect-[1000/620] min-h-0 w-full flex-1 xl:aspect-auto">
            <Stage
              view={view}
              speed={playback.speed}
              presenter={presenter}
              selectedAgent={agent}
              selectedFinding={tab === "findings" ? open : null}
              resultHref={resultHref}
              onSelectAgent={selectAgent}
              onSelectFinding={selectFinding}
              onSelectMessage={selectMessage}
              onSelectVerifier={() => {
                setTab("verifier");
                setOpen(null);
              }}
            />
          </div>
          {!presenter && <Legend />}
          <AnimatePresence>
            {presenter && view.announcement && (
              <motion.p
                key={view.announcement}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="glass absolute bottom-4 left-1/2 max-w-3xl -translate-x-1/2 px-5 py-3 text-center text-lg"
              >
                <Masked text={view.announcement} />
              </motion.p>
            )}
          </AnimatePresence>
        </section>

        {!presenter && (
          <Blackboard
            view={view}
            events={events}
            tab={tab}
            onTab={(next) => {
              setTab(next);
              setOpen(null);
            }}
            open={open}
            onOpen={setOpen}
            agent={agent}
            onClearAgent={() => setAgent(null)}
          />
        )}
      </div>

      <Timeline
        events={events}
        playback={playback}
        live={!ended}
        presenter={presenter}
        onPresenter={() => setPresenter((value) => !value)}
      />

      {view.ended === "aborted" && (
        <Notice title="This case stopped with an error">
          Its events are kept. No result was recorded.
        </Notice>
      )}
      {view.ended === "interrupted" && (
        <Notice title="This case did not finish">
          Nothing is running it now, for example after a restart. No result was recorded.
        </Notice>
      )}

      <div className="sr-only" aria-live="polite" role="status">
        {view.announcement}
      </div>
    </div>
  );
}
