"use client";

import { useState } from "react";
import {
  bounds,
  type ComparisonReport,
  groupsOf,
  type LevelReport,
  orderedSystems,
  reach,
  shown,
  signed,
  type StabilityReport,
  type SystemReport,
} from "@/lib/evaluation";
import { conditionName, RESULT_LOOK } from "@/lib/vocabulary";

const RESULTS = ["CONSISTENT", "CONFLICTS", "UNVERIFIED"];
/** Marks use one neutral hue, and the main comparison stands out by being brighter. */
const MAIN = new Set(["CREW-FULL", "SA-BASE"]);
const FRONTIER = { width: 620, height: 320, left: 48, right: 24, top: 16, bottom: 40 };

function Figure({ title, note, children }: { title: string; note: string; children: React.ReactNode }) {
  return (
    <figure className="glass flex min-w-0 flex-col gap-3 p-5">
      <figcaption>
        <h2 className="font-medium">{title}</h2>
        <p className="text-sm text-text-3">{note}</p>
      </figcaption>
      {children}
    </figure>
  );
}

function Whisker({ comparison, domain }: { comparison: ComparisonReport; domain: number }) {
  const place = (value: number) => ((value + domain) / (2 * domain)) * 100;
  const low = place(comparison.ci_low ?? 0);
  const high = place(comparison.ci_high ?? 0);
  return (
    <div className="relative h-6" aria-hidden>
      <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
      <span
        className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-text-3"
        style={{ left: `${low}%`, width: `${Math.max(high - low, 0.5)}%` }}
      />
      <span
        className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-rec ring-2 ring-lapis-900"
        style={{ left: `${place(comparison.difference ?? 0)}%` }}
      />
    </div>
  );
}

function Comparisons({
  title,
  note,
  comparisons,
}: {
  title: string;
  note: string;
  comparisons: ComparisonReport[];
}) {
  const shownRows = comparisons.filter((comparison) => comparison.pairs > 0);
  if (shownRows.length === 0) return null;
  const domain = reach(shownRows);
  return (
    <Figure title={title} note={note}>
      <ul className="flex flex-col gap-2" data-testid="comparisons">
        {shownRows.map((comparison) => (
          <li
            key={comparison.name}
            className="grid grid-cols-1 items-center gap-x-4 sm:grid-cols-[13rem_minmax(0,1fr)_11rem]"
          >
            <div className="min-w-0 text-[13px]">
              <p className="truncate text-text">{comparison.name}</p>
              <p className="text-xs text-text-3">
                {conditionName(comparison.first ?? "")} against{" "}
                {conditionName(comparison.second ?? "")}
              </p>
            </div>
            <Whisker comparison={comparison} domain={domain} />
            <p className="data text-xs text-text-2">
              {signed(comparison.difference)}
              <span className="text-text-3">
                {" "}
                p {shown(comparison.p_holm ?? comparison.p_value)}
                {comparison.p_holm !== undefined && " (Holm)"}
              </span>
            </p>
          </li>
        ))}
      </ul>
      <p className="data flex justify-between text-[11px] text-text-3" aria-hidden>
        <span>−{domain.toFixed(2)}</span>
        <span>0</span>
        <span>+{domain.toFixed(2)}</span>
      </p>
    </Figure>
  );
}

function Frontier({ systems }: { systems: [string, SystemReport][] }) {
  const placed = systems.filter(
    ([, s]) => s.macro_f1 !== null && s.compute.requests_per_case !== null,
  );
  const [hovered, setHovered] = useState<string | null>(null);
  if (placed.length === 0) return null;
  const { width, height, left, right, top, bottom } = FRONTIER;
  const most = Math.max(...placed.map(([, s]) => s.compute.requests_per_case ?? 0), 1);
  // A scatter needs no zero, and starting nearer the lowest system keeps the points apart.
  const lowest = Math.min(...placed.map(([, s]) => s.macro_f1 ?? 0));
  const floor = Math.max(0, Math.floor((lowest - 0.05) * 4) / 4);
  const ticks = [0, 1, 2, 3, 4].map((step) => step / 4).filter((tick) => tick >= floor);
  const x = (value: number) => left + (value / most) * (width - left - right);
  const y = (value: number) => top + ((1 - value) / (1 - floor)) * (height - top - bottom);
  const active = placed.find(([name]) => name === hovered);
  return (
    <Figure title="Quality against compute" note="Up and to the left is better.">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="Macro-F1 against model requests per case. The table below holds the same numbers.">
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke="var(--color-line)" />
            <text x={left - 8} y={y(tick) + 4} textAnchor="end" fontSize={11} fill="var(--color-text-3)" className="data">
              {tick.toFixed(2)}
            </text>
          </g>
        ))}
        {[0, most / 2, most].map((tick) => (
          <text key={tick} x={x(tick)} y={height - 22} textAnchor="middle" fontSize={11} fill="var(--color-text-3)" className="data">
            {tick.toFixed(0)}
          </text>
        ))}
        <text x={width - right} y={height - 4} textAnchor="end" fontSize={11} fill="var(--color-text-3)">
          Model requests per case
        </text>
        {placed.map(([name, system]) => {
          const cx = x(system.compute.requests_per_case ?? 0);
          const cy = y(system.macro_f1 ?? 0);
          const main = MAIN.has(name);
          return (
            <g
              key={name}
              data-testid="frontier-dot"
              onPointerEnter={() => setHovered(name)}
              onPointerLeave={() => setHovered(null)}
            >
              <title>{`${conditionName(name)}: macro-F1 ${shown(system.macro_f1)}, ${shown(system.compute.requests_per_case, 1)} requests per case`}</title>
              <circle cx={cx} cy={cy} r={12} fill="transparent" />
              <circle
                cx={cx}
                cy={cy}
                r={5}
                fill={main ? "var(--color-rec)" : "var(--color-text-3)"}
                stroke="var(--color-lapis-900)"
                strokeWidth={2}
              />
              {main && (
                <text
                  x={cx + 10}
                  y={cy - 8}
                  fontSize={12}
                  fill="var(--color-text)"
                  stroke="var(--color-lapis-900)"
                  strokeWidth={3}
                  paintOrder="stroke"
                >
                  {conditionName(name)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <p className="data h-4 text-xs text-text-2" aria-hidden>
        {active
          ? `${conditionName(active[0])}: macro-F1 ${shown(active[1].macro_f1)}, ${shown(active[1].compute.requests_per_case, 1)} requests per case`
          : ""}
      </p>
    </Figure>
  );
}

function FactorTable({ level }: { level: LevelReport }) {
  const groups = groupsOf(level);
  if (groups.length === 0) return null;
  return (
    <Figure
      title="Share right, by system"
      note="Exploratory, apart from the registered test of F1, F6 and F7. Darker cells are lower."
    >
      <div className="overflow-x-auto">
        <table className="w-full text-right text-xs" data-testid="factor-table">
          <caption className="sr-only">The share of items each system got right, by factor</caption>
          <thead>
            <tr className="text-text-3">
              <th scope="col" className="sr-only">
                System
              </th>
              {groups.map((group) => (
                <th key={group} scope="col" className="data w-[8%] px-1 pb-1 font-normal">
                  {group}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {orderedSystems(level).map(([name, system]) => (
              <tr key={name}>
                <th scope="row" className="pr-3 text-left text-[13px] font-normal whitespace-nowrap text-text-2">
                  {conditionName(name)}
                </th>
                {groups.map((group) => {
                  const score = system.by_group[group];
                  const share = score?.accuracy ?? null;
                  return (
                    <td
                      key={group}
                      className="data p-1 text-text"
                      style={{
                        background:
                          share === null
                            ? undefined
                            : `color-mix(in srgb, var(--color-consistent) ${Math.round(share * 45)}%, transparent)`,
                      }}
                      title={score ? `${score.items} items` : undefined}
                    >
                      {share === null ? "–" : Math.round(share * 100)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Figure>
  );
}

function Confusion({ systems }: { systems: [string, SystemReport][] }) {
  const [chosen, setChosen] = useState(
    systems.find(([name]) => name === "CREW-FULL")?.[0] ?? systems[0]?.[0] ?? "",
  );
  const system = systems.find(([name]) => name === chosen)?.[1];
  if (!system) return null;
  return (
    <Figure title="What each result became" note="Rows are the labels, and columns the answers.">
      <label className="flex items-center gap-2 text-sm text-text-2">
        System
        <select
          className="field h-9 w-auto px-2 text-sm"
          value={chosen}
          onChange={(event) => setChosen(event.target.value)}
        >
          {systems.map(([name]) => (
            <option key={name} value={name}>
              {conditionName(name)}
            </option>
          ))}
        </select>
      </label>
      <table className="w-full text-sm" data-testid="confusion">
        <caption className="sr-only">Labels against answers for {conditionName(chosen)}</caption>
        <thead>
          <tr className="text-xs text-text-3">
            <th scope="col" className="sr-only">
              Label
            </th>
            {RESULTS.map((result) => (
              <th key={result} scope="col" className="p-1 text-right font-normal">
                {RESULT_LOOK[result]?.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {RESULTS.map((gold) => (
            <tr key={gold} className="border-t border-line">
              <th scope="row" className="p-1 text-left font-normal text-text-2">
                {RESULT_LOOK[gold]?.label}
              </th>
              {RESULTS.map((result) => (
                <td
                  key={result}
                  className={`data p-1 text-right ${gold === result ? "text-text" : "text-text-3"}`}
                >
                  {system.confusion[gold]?.[result] ?? 0}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Figure>
  );
}

/** Every system's headline numbers, and what a chart cannot show: the cases with no answer. */
function Systems({ systems }: { systems: [string, SystemReport][] }) {
  if (systems.length === 0) return null;
  const columns = [
    "Items",
    "No result",
    "Not run",
    "False reassurance",
    "Macro-F1",
    "Coverage",
    "Requests per case",
  ];
  return (
    <Figure
      title="Every system"
      note='Brackets hold a 95% interval. A case that gave no result is scored as "Could not verify".'
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[42rem] text-right text-sm" data-testid="systems">
          <caption className="sr-only">Headline numbers for each system</caption>
          <thead>
            <tr className="text-xs text-text-3">
              <th scope="col" className="p-1 text-left font-normal">
                System
              </th>
              {columns.map((column) => (
                <th key={column} scope="col" className="p-1 font-normal">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {systems.map(([name, system]) => (
              <tr key={name} className="border-t border-line">
                <th scope="row" className="p-1 text-left font-normal text-text-2">
                  {conditionName(name)}
                </th>
                <td className="data p-1">{system.items}</td>
                <td className="data p-1">{system.failures}</td>
                <td className="data p-1">{system.not_yet_run}</td>
                <td className="data p-1">
                  {shown(system.false_reassurance_rate)}{" "}
                  <span className="text-text-3">
                    {bounds(system.intervals.false_reassurance_rate)}
                  </span>
                </td>
                <td className="data p-1">
                  {shown(system.macro_f1)}{" "}
                  <span className="text-text-3">{bounds(system.intervals.macro_f1)}</span>
                </td>
                <td className="data p-1">{shown(system.coverage)}</td>
                <td className="data p-1">{shown(system.compute.requests_per_case, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Figure>
  );
}

function Stability({ rows }: { rows: StabilityReport[] }) {
  const measured = rows.filter((row) => row.items > 0);
  if (measured.length === 0) return null;
  return (
    <Figure title="Repeat runs" note="How far a system agrees with itself on the same items.">
      <ul className="flex flex-col gap-1 text-sm" data-testid="stability">
        {measured.map((row) => (
          <li key={row.condition} className="flex justify-between gap-4 border-t border-line pt-1">
            <span className="text-text-2">{conditionName(row.condition)}</span>
            <span className="data text-xs">
              kappa {shown(row.fleiss_kappa)}, changed answer on {shown(row.flip_rate)} of{" "}
              {row.items} items
            </span>
          </li>
        ))}
      </ul>
    </Figure>
  );
}

const MECHANISMS: [string, string][] = [
  ["conflicts_per_case", "Conflicts per case"],
  ["challenges_per_case", "Challenges per case"],
  ["revision_rate", "Challenges that led to a revision"],
  ["veto_rate", "Cases with a veto"],
  ["veto_precision", "Vetoed proposals that were wrong"],
  ["veto_recall", "Wrong \"Consistent\" proposals vetoed"],
  ["rescue_rate", "Wrong first proposals that ended right"],
];

function Mechanisms({ systems }: { systems: [string, SystemReport][] }) {
  const crews = systems.filter(([name]) => name.startsWith("CREW"));
  if (crews.length === 0) return null;
  return (
    <Figure title="How the mechanisms behaved" note="Each measure over the crew conditions.">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[30rem] text-right text-sm" data-testid="mechanisms">
          <caption className="sr-only">Coordination measures for each crew condition</caption>
          <thead>
            <tr className="text-xs text-text-3">
              <th scope="col" className="sr-only">
                Measure
              </th>
              {crews.map(([name]) => (
                <th key={name} scope="col" className="p-1 font-normal">
                  {conditionName(name)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {MECHANISMS.map(([key, label]) => (
              <tr key={key} className="border-t border-line">
                <th scope="row" className="p-1 text-left font-normal text-text-2">
                  {label}
                </th>
                {crews.map(([name, system]) => (
                  <td key={name} className="data p-1">
                    {shown(system.coordination[key], 2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Figure>
  );
}

function Headline({ level }: { level: LevelReport }) {
  const { interaction, non_inferiority: inferiority } = level;
  return (
    <div className="glass grid gap-4 p-5 sm:grid-cols-3">
      <div>
        <p className="eyebrow">Items</p>
        <p className="data mt-1 text-2xl">{level.items}</p>
      </div>
      <div>
        <p className="eyebrow">H2, at least as useful</p>
        <p className="mt-1 text-sm">
          {inferiority.tested
            ? `${inferiority.holds ? "Holds" : "Does not hold"}: lower bound ${signed(inferiority.ci_low)}, margin −${shown(inferiority.margin, 2)}`
            : "Not tested yet"}
        </p>
      </div>
      <div>
        <p className="eyebrow">H5, gain on F1, F6 and F7</p>
        <p className="mt-1 text-sm">
          {interaction.tested
            ? `${signed(interaction.difference)} [${signed(interaction.ci_low)}, ${signed(interaction.ci_high)}]`
            : "Not tested yet"}
        </p>
      </div>
    </div>
  );
}

/** One level of the evaluation. A level is always shown alone, and never added to the other. */
export function EvaluationCharts({ level }: { level: LevelReport }) {
  const systems = orderedSystems(level);
  const [frr, usefulness] = [
    (c: ComparisonReport) => c.metric === "false_reassurance",
    (c: ComparisonReport) => c.metric === "macro_f1",
  ];
  const all = [...level.registered, ...level.secondary];
  return (
    <div className="flex flex-col gap-4" data-testid="evaluation-charts">
      <Headline level={level} />
      <Systems systems={systems} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Comparisons
          title="False reassurance"
          note="Difference between two systems. Left of zero, the first reassures falsely less."
          comparisons={all.filter(frr)}
        />
        <Comparisons
          title="Macro-F1"
          note="Difference between two systems. Right of zero, the first is more useful."
          comparisons={all.filter(usefulness)}
        />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Frontier systems={systems} />
        <Confusion systems={systems} />
      </div>
      <FactorTable level={level} />
      <Mechanisms systems={systems} />
      <Stability rows={level.stability} />
    </div>
  );
}
