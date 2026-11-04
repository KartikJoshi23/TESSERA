"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Masked } from "@/components/Masked";
import { ResultBadge } from "@/components/ResultMark";
import { Stage } from "@/components/theater/Stage";
import { ApiOffline, Notice, PageTitle } from "@/components/ui";
import { api, type CaseSummary } from "@/lib/api";
import {
  claimDifference,
  type Metrics,
  metricsOf,
  pairsIn,
  type Step,
  stepsOf,
} from "@/lib/compare";
import type { CaseEvent } from "@/lib/events";
import { useCaseEvents, useLoad } from "@/lib/hooks";
import { type CaseView, fold } from "@/lib/reducer";
import { conditionName, isCrew } from "@/lib/vocabulary";

interface Run {
  id: string;
  view: CaseView;
  events: CaseEvent[];
  metrics: Metrics;
}

function useRun(id: string): Run {
  const { events } = useCaseEvents(id);
  const view = useMemo(() => fold(events), [events]);
  const metrics = useMemo(() => metricsOf(view, events), [view, events]);
  return { id, view, events, metrics };
}

const STEP_COLOR: Record<Step["kind"], string> = {
  request: "var(--color-sa)",
  tool: "var(--color-cma)",
  finding: "var(--color-text-3)",
  verdict: "var(--color-ver)",
  result: "var(--color-text)",
};

function LinearTimeline({ events }: { events: CaseEvent[] }) {
  const steps = useMemo(() => stepsOf(events), [events]);
  if (steps.length === 0) {
    return <p className="py-10 text-center text-sm text-text-3">Waiting for the first step.</p>;
  }
  return (
    <ol className="pane-scroll flex max-h-[26rem] flex-col px-1" data-testid="linear-timeline">
      {steps.map((step) => (
        <li key={step.key} className="relative flex gap-3 pb-3 pl-4">
          <span
            aria-hidden
            className="absolute top-1.5 left-0 size-2 rounded-full"
            style={{ background: STEP_COLOR[step.kind] }}
          />
          <span aria-hidden className="absolute top-4 bottom-0 left-[3.5px] w-px bg-line" />
          <span className="min-w-0">
            <span className="data block truncate text-[13px] text-text">{step.title}</span>
            {step.detail && (
              <span className="data block truncate text-[11px] text-text-3">{step.detail}</span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Side({ run, label }: { run: Run; label: string }) {
  const { view, id } = run;
  return (
    <section className="glass flex min-w-0 flex-col gap-3 p-4" aria-label={label}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <p className="eyebrow">{label}</p>
          <h2 className="mt-1 truncate font-medium">{conditionName(view.condition) || "…"}</h2>
        </div>
        <Link href={`/cases/${encodeURIComponent(id)}`} className="text-sm text-text-2 hover:text-text">
          Open in the Theater
        </Link>
      </header>
      {isCrew(view.condition) ? (
        <div className="relative aspect-[1000/620] w-full">
          <Stage view={view} compact />
        </div>
      ) : (
        <div className="min-h-[16rem] flex-1">
          <LinearTimeline events={run.events} />
        </div>
      )}
      <div className="border-t border-line pt-3" data-testid="arena-result">
        <ResultBadge result={view.final?.result} />
      </div>
    </section>
  );
}

const ROWS: { key: keyof Metrics; label: string; unit?: string }[] = [
  { key: "requests", label: "Model requests" },
  { key: "tokens", label: "Tokens" },
  { key: "toolCalls", label: "Tool calls" },
  { key: "seconds", label: "Time", unit: "s" },
  { key: "findings", label: "Findings" },
  { key: "messages", label: "Messages" },
  { key: "conflicts", label: "Conflicts" },
  { key: "vetoes", label: "Vetoes" },
];

function Bar({ value, largest }: { value: number; largest: number }) {
  return (
    <span aria-hidden className="mt-1 block h-1 w-full max-w-44 overflow-hidden">
      <span
        className="block h-full rounded-r-[4px] bg-text-3"
        style={{ width: `${largest ? (value / largest) * 100 : 0}%` }}
      />
    </span>
  );
}

function CostTable({ a, b }: { a: Run; b: Run }) {
  return (
    <section className="glass overflow-x-auto p-5" aria-labelledby="cost">
      <h2 id="cost" className="eyebrow mb-3">
        What each one spent
      </h2>
      <table className="w-full min-w-[32rem] text-left text-sm">
        <caption className="sr-only">The same measures for both systems</caption>
        <thead>
          <tr className="text-xs text-text-3">
            <th scope="col" className="w-1/3 py-1.5 font-medium">
              Measure
            </th>
            <th scope="col" className="py-1.5 pr-6 font-medium">
              {conditionName(a.view.condition)}
            </th>
            <th scope="col" className="py-1.5 font-medium">
              {conditionName(b.view.condition)}
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(({ key, label, unit }) => {
            const left = a.metrics[key];
            const right = b.metrics[key];
            const largest = Math.max(left ?? 0, right ?? 0);
            return (
              <tr key={key} className="border-t border-line">
                <th scope="row" className="py-2 font-normal text-text-2">
                  {label}
                </th>
                {[left, right].map((value, index) => (
                  <td key={index === 0 ? "a" : "b"} className="py-2 pr-6">
                    <span className="data block">
                      {value === null ? "…" : `${value.toLocaleString("en")}${unit ?? ""}`}
                    </span>
                    <Bar value={value ?? 0} largest={largest} />
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function ClaimColumn({ title, claims }: { title: string; claims: string[] }) {
  return (
    <div className="min-w-0">
      <h3 className="text-sm font-medium">
        {title} <span className="data text-text-3">{claims.length}</span>
      </h3>
      <ul className="mt-2 flex flex-col gap-1.5">
        {claims.map((claim) => (
          <li key={claim} className="glass-thin px-2.5 py-1.5 text-[13px] leading-snug text-text-2">
            <Masked text={claim} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ClaimDifference({ a, b }: { a: Run; b: Run }) {
  if (!a.view.final || !b.view.final) return null;
  const difference = claimDifference(a.view, b.view);
  return (
    <section className="glass p-5" aria-labelledby="claims" data-testid="claim-difference">
      <h2 id="claims" className="eyebrow mb-3">
        Where their claims differ
      </h2>
      <div className="grid gap-4 md:grid-cols-3">
        <ClaimColumn title="System A only" claims={difference.onlyA} />
        <ClaimColumn title="Both" claims={difference.both} />
        <ClaimColumn title="System B only" claims={difference.onlyB} />
      </div>
    </section>
  );
}

function Duel({ a, b }: { a: string; b: string }) {
  const left = useRun(a);
  const right = useRun(b);
  return (
    <div className="mx-auto flex w-full max-w-[1680px] flex-col gap-4 px-4 pb-8 lg:px-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="display text-2xl">Arena</h1>
        <p className="text-sm text-text-3">
          One case shows how they differ. Only the Lab can say which does better.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Side run={left} label="System A" />
        <Side run={right} label="System B" />
      </div>
      <CostTable a={left} b={right} />
      <ClaimDifference a={left} b={right} />
    </div>
  );
}

function label(item: CaseSummary): string {
  return `${item.case_id} · ${conditionName(item.condition)}`;
}

function Picker() {
  const router = useRouter();
  const { data, error } = useLoad(api.cases);
  const finished = useMemo(() => (data ?? []).filter((item) => item.result), [data]);
  const pairs = useMemo(() => pairsIn(finished.map((item) => item.case_id)), [finished]);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const open = () =>
    router.push(`/arena?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
      <PageTitle eyebrow="Arena" title="Crew against single agent">
        The same offer, the same tools and the same model. Only the orchestration differs. A single
        agent doing as well would be a valid result.
      </PageTitle>
      {error && <ApiOffline message={error.message} />}
      {data && finished.length < 2 && (
        <Notice title="Nothing to compare yet">
          Run both on one offer from{" "}
          <Link href="/intake" className="underline">
            Intake
          </Link>
          .
        </Notice>
      )}
      {pairs.length > 0 && (
        <section className="glass p-5" aria-labelledby="pairs">
          <h2 id="pairs" className="eyebrow mb-3">
            Both systems ran these
          </h2>
          <ul className="flex flex-wrap gap-1.5">
            {pairs.map((pair) => (
              <li key={pair.name}>
                <Link
                  href={`/arena?a=${encodeURIComponent(pair.a)}&b=${encodeURIComponent(pair.b)}`}
                  className="data inline-flex h-8 items-center rounded-md border border-line px-2.5 text-sm hover:border-line-strong"
                >
                  {pair.name}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      {finished.length >= 2 && (
        <section className="glass flex flex-col gap-3 p-5" aria-label="Choose two cases">
          {[
            { id: "system-a", title: "System A", value: a, set: setA },
            { id: "system-b", title: "System B", value: b, set: setB },
          ].map((field) => (
            <div key={field.id}>
              <label htmlFor={field.id} className="eyebrow mb-1.5 block">
                {field.title}
              </label>
              <select
                id={field.id}
                className="field h-10 px-3 text-sm"
                value={field.value}
                onChange={(event) => field.set(event.target.value)}
              >
                <option value="">Choose a finished case</option>
                {finished.map((item) => (
                  <option key={item.case_id} value={item.case_id}>
                    {label(item)}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <button
            type="button"
            className="button button-primary self-start"
            disabled={!a || !b || a === b}
            onClick={open}
          >
            Compare <ArrowRight size={15} aria-hidden />
          </button>
        </section>
      )}
    </div>
  );
}

/** Both sides are chosen in the address, so a comparison can be reopened or passed on. */
export function Arena() {
  const params = useSearchParams();
  const a = params.get("a");
  const b = params.get("b");
  return a && b ? <Duel key={`${a}|${b}`} a={a} b={b} /> : <Picker />;
}
