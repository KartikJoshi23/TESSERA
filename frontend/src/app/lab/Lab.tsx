"use client";

import { useMemo, useState } from "react";
import { Notice, PageTitle } from "@/components/ui";
import pilot from "@/data/pilot-comparison.json";
import pilotReport from "@/data/pilot-report.json";
import smoke from "@/data/smoke-comparison.json";
import evaluation from "@/data/evaluation.json";
import type { EvaluationReport } from "@/lib/evaluation";
import { type SmokeCase, type SmokeRow, type SmokeRun, summarize } from "@/lib/smoke";
import { conditionName, RESULT_LOOK } from "@/lib/vocabulary";
import { EvaluationCharts } from "./Charts";

/** Empty until Part 7. It holds aggregates only, so it can be committed after a release review. */
const FINAL = evaluation as EvaluationReport;
const PILOT = pilotReport as EvaluationReport;

type Tab = "entity" | "message" | "smoke";

const TABS: { id: Tab; label: string }[] = [
  { id: "entity", label: "Entity-level (real records)" },
  { id: "message", label: "Message-level (synthetic)" },
  { id: "smoke", label: "Development runs" },
];

/** Stepped down from the result colours for filled marks, and checked against this surface. */
const CELL_COLOR: Record<string, string> = {
  CONSISTENT: "#14a08f",
  CONFLICTS: "#c98500",
  UNVERIFIED: "#7a86ea",
};

const CONDITION_ORDER = [
  "RULES-ONLY",
  "SA-BASE",
  "SA-VER",
  "SA-SC5",
  "SA-MAX",
  "SA-LARGER",
  "CREW-SILO",
  "CREW-SHARE",
  "CREW-FULL",
  "CREW-NV",
];

function NoResults({ title }: { title: string }) {
  return (
    <Notice title={`${title}: no results yet`}>
      The evaluation runs in the next part, once the test data has been recorded by hand. Results
      from real records and from synthetic messages are reported apart, and never pooled.
    </Notice>
  );
}

function BarRow({
  label,
  value,
  largest,
  text,
  emphasis,
}: {
  label: string;
  value: number;
  largest: number;
  text: string;
  emphasis: boolean;
}) {
  return (
    <div className="grid grid-cols-[10rem_minmax(0,1fr)] items-center gap-3" title={`${label}: ${text}`}>
      <span className="truncate text-[13px] text-text-2">{label}</span>
      <span className="flex min-w-0 items-center gap-2">
        <span
          className={`h-3 rounded-r-[4px] ${emphasis ? "bg-rec" : "bg-text-3"}`}
          style={{ width: `${largest ? (value / largest) * 85 : 0}%`, minWidth: value ? 2 : 0 }}
        />
        <span className="data shrink-0 text-xs text-text">{text}</span>
      </span>
    </div>
  );
}

function Bars({
  title,
  note,
  rows,
  value,
  text,
  largest,
}: {
  title: string;
  note: string;
  rows: SmokeRow[];
  value: (row: SmokeRow) => number;
  text: (row: SmokeRow) => string;
  largest?: number;
}) {
  const top = largest ?? Math.max(...rows.map(value), 1);
  return (
    <figure className="glass flex flex-col gap-3 p-5">
      <figcaption>
        <h2 className="font-medium">{title}</h2>
        <p className="text-sm text-text-3">{note}. The main comparison is the brighter pair.</p>
      </figcaption>
      <div className="flex flex-col gap-2">
        {rows.map((row) => (
          <BarRow
            key={row.run}
            label={conditionName(row.condition)}
            value={value(row)}
            largest={top}
            text={text(row)}
            emphasis={row.condition === "CREW-FULL" || row.condition === "SA-BASE"}
          />
        ))}
      </div>
    </figure>
  );
}

interface Hovered {
  item: SmokeCase;
  condition: string;
}

function Cell({ item, onHover }: { item: SmokeCase; onHover: (item: SmokeCase | null) => void }) {
  const differs = item.result !== item.gold;
  return (
    <td className="p-px">
      <span
        className="relative block size-[18px] rounded-[3px]"
        style={{ background: CELL_COLOR[item.result] ?? "transparent" }}
        onPointerEnter={() => onHover(item)}
        onPointerLeave={() => onHover(null)}
        data-testid="smoke-cell"
      >
        {differs && (
          <span aria-hidden className="absolute inset-[5px] rounded-[2px] bg-lapis-950" />
        )}
        <span className="sr-only">
          {item.case}: {RESULT_LOOK[item.result]?.label ?? item.result}
          {differs ? `, hand label ${RESULT_LOOK[item.gold]?.label ?? item.gold}` : ""}
        </span>
      </span>
    </td>
  );
}

function Matrix({ rows }: { rows: SmokeRow[] }) {
  const [hovered, setHovered] = useState<Hovered | null>(null);
  // Systems can have run different cases, so a column is found by name and never by position.
  const names = [...new Set(rows.flatMap((row) => row.cases.map((item) => item.case)))].sort();
  return (
    <figure className="glass flex flex-col gap-3 p-5">
      <figcaption>
        <h2 className="font-medium">Every case, by system</h2>
        <p className="text-sm text-text-3">
          Colour is the result given. A dark centre means it differs from the hand label.
        </p>
      </figcaption>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-2" aria-label="Key">
        {Object.entries(CELL_COLOR).map(([result, color]) => (
          <li key={result} className="flex items-center gap-1.5">
            <span aria-hidden className="size-3 rounded-[3px]" style={{ background: color }} />
            {RESULT_LOOK[result]?.label}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="relative size-3 rounded-[3px] bg-text-3">
            <span className="absolute inset-[3.5px] rounded-[1px] bg-lapis-950" />
          </span>
          Differs from the hand label
        </li>
      </ul>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-0">
          <caption className="sr-only">
            The result each system gave on each of the fictional cases
          </caption>
          <thead>
            <tr>
              <th scope="col" className="sr-only">
                System
              </th>
              {names.map((name) => (
                <th key={name} scope="col" className="data px-px pb-1 text-[9px] font-normal text-text-3">
                  {name.replace(/^M-/, "").replace(/^S/, "").replace(/^[A-Z]+-0*/, "")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.run}>
                <th scope="row" className="pr-3 text-left text-[13px] font-normal whitespace-nowrap text-text-2">
                  {conditionName(row.condition)}
                </th>
                {names.map((name) => {
                  const item = row.cases.find((entry) => entry.case === name);
                  return item ? (
                    <Cell
                      key={name}
                      item={item}
                      onHover={(value) =>
                        setHovered(value && { item: value, condition: row.condition })
                      }
                    />
                  ) : (
                    <td key={name} className="p-px">
                      <span className="sr-only">{name}: not run</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="data h-4 text-xs text-text-2" aria-hidden>
        {hovered
          ? `${hovered.item.case} · ${conditionName(hovered.condition)} · ${RESULT_LOOK[hovered.item.result]?.label ?? hovered.item.result} · hand label: ${RESULT_LOOK[hovered.item.gold]?.label ?? hovered.item.gold} · ${hovered.item.requests} requests`
          : ""}
      </p>
    </figure>
  );
}

function SummaryTable({ rows }: { rows: SmokeRow[] }) {
  return (
    <div className="glass overflow-x-auto p-5">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <caption className="sr-only">The same counts for every system</caption>
        <thead>
          <tr className="text-xs text-text-3">
            <th scope="col" className="py-1.5 font-medium">
              System
            </th>
            <th scope="col" className="py-1.5 text-right font-medium">
              Agrees with label
            </th>
            <th scope="col" className="py-1.5 text-right font-medium">
              False reassurance
            </th>
            <th scope="col" className="py-1.5 text-right font-medium">
              Over-cautious
            </th>
            <th scope="col" className="py-1.5 text-right font-medium">
              Requests
            </th>
            <th scope="col" className="py-1.5 text-right font-medium">
              Tokens
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.run} className="border-t border-line">
              <th scope="row" className="py-2 font-normal">
                {conditionName(row.condition)}
              </th>
              <td className="data py-2 text-right">
                {row.agreed}/{row.total}
              </td>
              <td className="data py-2 text-right">{row.falseReassurance}</td>
              <td className="data py-2 text-right">{row.overCautious}</td>
              <td className="data py-2 text-right">{row.requests.toLocaleString("en")}</td>
              <td className="data py-2 text-right">{row.tokens.toLocaleString("en")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const DEVELOPMENT_SETS = {
  pilot: {
    label: "Fictional pilot",
    runs: pilot.runs as SmokeRun[],
    note: "Generated offers about the fictional firms, worded to hide the facts. Plain rules find these hard, so they say more than the smoke set, but they are still development data.",
  },
  smoke: {
    label: "Smoke set",
    runs: smoke.runs as SmokeRun[],
    note: "Fictional cases written by hand to test the build. They are too easy: rules alone get most of them right.",
  },
};

type DevelopmentSet = keyof typeof DEVELOPMENT_SETS;

function SmokeResults() {
  const [chosen, setChosen] = useState<DevelopmentSet>(pilot.runs.length ? "pilot" : "smoke");
  const set = DEVELOPMENT_SETS[chosen];
  const rows = useMemo(() => {
    const summaries = set.runs.map(summarize);
    const rank = (row: SmokeRow) => {
      const index = CONDITION_ORDER.indexOf(row.condition);
      return index === -1 ? CONDITION_ORDER.length : index;
    };
    return summaries.sort((a, b) => rank(a) - rank(b) || a.run.localeCompare(b.run));
  }, [set]);
  return (
    <div className="flex flex-col gap-4" data-testid="smoke-results">
      <div role="group" aria-label="Development set" className="flex gap-1">
        {(Object.keys(DEVELOPMENT_SETS) as DevelopmentSet[]).map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={chosen === key}
            onClick={() => setChosen(key)}
            className={`cursor-pointer rounded-lg border px-3 py-1 text-sm ${
              chosen === key
                ? "border-line-strong bg-white/10 text-text"
                : "border-line text-text-2 hover:text-text"
            }`}
          >
            {DEVELOPMENT_SETS[key].label}
          </button>
        ))}
      </div>
      <Notice title="Development numbers only" tone="caution">
        {set.note} They say nothing about final performance.
      </Notice>
      {rows.length === 0 ? (
        <Notice title="No finished runs yet">Nothing has finished on this set.</Notice>
      ) : (
        <>
          {chosen === "pilot" && PILOT.levels.message && (
            <EvaluationCharts level={PILOT.levels.message} />
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <Bars
              title="Agreement with the hand labels"
              note="Cases out of the total"
              rows={rows}
              value={(row) => row.agreed}
              text={(row) => `${row.agreed}/${row.total}`}
              largest={Math.max(...rows.map((row) => row.total))}
            />
            <Bars
              title="Model requests"
              note="Across the whole set"
              rows={rows}
              value={(row) => row.requests}
              text={(row) => row.requests.toLocaleString("en")}
            />
          </div>
          <Matrix rows={rows} />
          <SummaryTable rows={rows} />
        </>
      )}
    </div>
  );
}

/** The research results. The two levels of evaluation stay on separate tabs, and are never pooled. */
export function Lab() {
  const [tab, setTab] = useState<Tab>("smoke");
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 py-6 lg:px-6">
      <PageTitle eyebrow="Evaluation Lab" title="How well does it work?">
        Checks on real register and alert records, and checks on labelled synthetic messages, answer
        different questions. They are measured and reported apart.
      </PageTitle>

      <div role="tablist" aria-label="Evaluation" className="glass-thin flex w-fit max-w-full flex-wrap gap-1 p-1">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            role="tab"
            type="button"
            id={`lab-${id}`}
            aria-selected={tab === id}
            aria-controls="lab-panel"
            onClick={() => setTab(id)}
            className={`cursor-pointer rounded-lg px-3 py-1.5 text-sm ${
              tab === id ? "bg-white/10 font-medium text-text" : "text-text-2 hover:text-text"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div id="lab-panel" role="tabpanel" aria-labelledby={`lab-${tab}`}>
        {tab === "entity" &&
          (FINAL.levels.entity ? (
            <EvaluationCharts level={FINAL.levels.entity} />
          ) : (
            <NoResults title="Entity-level evaluation" />
          ))}
        {tab === "message" &&
          (FINAL.levels.message ? (
            <EvaluationCharts level={FINAL.levels.message} />
          ) : (
            <NoResults title="Message-level evaluation" />
          ))}
        {tab === "smoke" && <SmokeResults />}
      </div>
    </div>
  );
}
