"use client";

import { ArrowLeft, Check, Download, ExternalLink, Minus, ShieldAlert } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useCallback, useMemo } from "react";
import { RESULT_ICON } from "@/components/ResultMark";
import { hexPoints, hexRing } from "@/components/theater/geometry";
import { Masked } from "@/components/Masked";
import { ApiOffline, Notice, SyntheticBadge } from "@/components/ui";
import { api, type Chip, type Report } from "@/lib/api";
import { saveJson } from "@/lib/download";
import { useCaseEvents, useLoad } from "@/lib/hooks";
import { type CaseView, fold } from "@/lib/reducer";
import { AGENT_LOOK, conditionName, CONFLICT_LABEL, resultLook } from "@/lib/vocabulary";

const KIND_LABEL: Record<string, string> = {
  register_entry: "Register entry",
  no_match: "No match found",
  alert_entry: "Alert entry",
  warning_entry: "Warning entry",
  unlicensed_entry: "Unlicensed list entry",
  rule_card: "Rule card",
  derived_analysis: "Derived from the offer",
};

/** Evidence with no source policy of its own. */
const SOURCE_LABEL: Record<string, string> = {
  rule_cards: "Rule cards",
  derived: "This analysis",
  offer: "The offer",
};

const TILE_RADIUS = 15;
const TILE_SPACING = TILE_RADIUS * Math.sqrt(3) + 2.5;
const TILE = hexPoints(TILE_RADIUS);
const MOSAIC_RINGS = 3;

/** Where each claim's tile goes: the centre, then ring after ring. */
function mosaicPlaces(count: number) {
  const places = [{ x: 0, y: 0 }];
  for (let ring = 1; ring <= MOSAIC_RINGS && places.length < count; ring += 1) {
    places.push(...hexRing(ring, TILE_SPACING));
  }
  return places.slice(0, count);
}

function tileColor(claim: Report["claims"][number]): string {
  const source = claim.evidence[0]?.source ?? "";
  if (source.startsWith("CMA")) return AGENT_LOOK.CMA.color;
  if (source.startsWith("DFSA")) return AGENT_LOOK.DFSA.color;
  if (source.startsWith("VARA")) return AGENT_LOOK.VARA.color;
  return AGENT_LOOK.CLN.color;
}

/** One tile per claim, coloured by the regulator whose record it rests on. */
function ClaimMosaic({ report }: { report: Report }) {
  const reduced = useReducedMotion();
  const places = mosaicPlaces(report.claims.length);
  if (places.length === 0) return null;
  return (
    <svg viewBox="-112 -100 224 200" className="hidden w-44 shrink-0 md:block" aria-hidden>
      {places.map((place, index) => {
        const claim = report.claims[index];
        if (!claim) return null;
        const color = tileColor(claim);
        return (
          <motion.g
            // Places are fixed, so a tile's position identifies it.
            key={`${place.x},${place.y}`}
            initial={
              reduced
                ? { x: place.x, y: place.y, opacity: 1 }
                : { x: place.x * 3, y: place.y * 3, opacity: 0, scale: 0.4 }
            }
            animate={{ x: place.x, y: place.y, opacity: 1, scale: 1 }}
            transition={{
              type: "spring",
              stiffness: 70,
              damping: 14,
              delay: reduced ? 0 : Math.min(index * 0.06, 0.8),
            }}
          >
            <polygon points={TILE} fill={color} fillOpacity={0.7} stroke={color} />
          </motion.g>
        );
      })}
    </svg>
  );
}

function ResultHero({ report }: { report: Report }) {
  const look = resultLook(report.result);
  const Icon = RESULT_ICON[report.result];
  const reduced = useReducedMotion();
  return (
    <motion.section
      initial={reduced ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className="glass overflow-hidden p-6 sm:p-8"
      style={{ borderColor: look?.color }}
      data-testid="result-hero"
      data-result={report.result}
      aria-label="Result"
    >
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
        {Icon && <Icon size={72} strokeWidth={1.1} color={look?.color} aria-hidden className="shrink-0" />}
        <div className="min-w-0">
          <p className="eyebrow">Result</p>
          <h1 className="display mt-2 text-2xl sm:text-3xl" style={{ color: look?.color }}>
            {report.wording}
          </h1>
          <p className="mt-3 max-w-3xl leading-relaxed text-text" dir="auto">
            <Masked text={report.explanation} />
          </p>
          <div className="mt-4 flex flex-col gap-2">
            {[...report.hard_conflicts, ...report.unverified_reasons].map((line) => (
              <p key={line.id} className="flex items-baseline gap-2 text-sm text-text-2">
                <span className="data shrink-0 text-xs text-text-3">{line.id}</span>
                {line.text}
              </p>
            ))}
          </div>
        </div>
        <div className="ml-auto self-center">
          <ClaimMosaic report={report} />
        </div>
      </div>
    </motion.section>
  );
}

function EvidenceChip({ chip }: { chip: Chip }) {
  const label = KIND_LABEL[chip.kind] ?? chip.kind.replaceAll("_", " ");
  const inner = (
    <>
      <span className="font-medium text-text">{SOURCE_LABEL[chip.source] ?? chip.source}</span>
      <span className="text-text-3">{label}</span>
      {chip.dated && <span className="data text-text-2">dated {chip.dated}</span>}
      {chip.as_of && <span className="data text-text-3">as of {chip.as_of}</span>}
      {chip.link && <ExternalLink size={12} aria-hidden className="text-text-3" />}
    </>
  );
  const style =
    "glass-thin inline-flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded-lg! px-2 py-1 text-xs";
  // Links come only from the backend, which allows a DFSA link to its homepage and nowhere else.
  return chip.link ? (
    <a href={chip.link} target="_blank" rel="noopener noreferrer" className={`${style} hover:border-line-strong`}>
      {inner}
    </a>
  ) : (
    <span className={style}>{inner}</span>
  );
}

function Claims({ report }: { report: Report }) {
  const reduced = useReducedMotion();
  if (report.claims.length === 0) {
    return <p className="text-sm text-text-3">This result states no claims from the records.</p>;
  }
  return (
    <ol className="grid gap-2 lg:grid-cols-2">
      {report.claims.map((claim, index) => (
        <motion.li
          // Claims never move, so their place in the list identifies them.
          key={index}
          initial={reduced ? false : { opacity: 0, y: 10, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.35, delay: reduced ? 0 : Math.min(index * 0.05, 0.6) }}
          className="glass-thin flex flex-col gap-2 p-3"
          data-testid="claim"
        >
          <p className="text-sm leading-relaxed" dir="auto">
            <Masked text={claim.text} />
          </p>
          {claim.evidence.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {claim.evidence.map((chip) => (
                <EvidenceChip key={chip.evidence_id} chip={chip} />
              ))}
            </div>
          )}
        </motion.li>
      ))}
    </ol>
  );
}

const RELEVANCE_LABEL: Record<string, string> = {
  primary: "Primary",
  possible: "Possible",
  not_indicated: "Not indicated",
  excluded: "Excluded",
};

function Coverage({ report }: { report: Report }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Which regulators were relevant, and which were checked</caption>
        <thead>
          <tr className="text-xs text-text-3">
            <th scope="col" className="py-2 pr-4 font-medium">
              Regulator
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Relevance
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Records checked
            </th>
            <th scope="col" className="py-2 font-medium">
              Why
            </th>
          </tr>
        </thead>
        <tbody>
          {report.regulators.map((row) => (
            <tr key={row.regulator} className="border-t border-line">
              <th scope="row" className="py-2 pr-4 font-medium">
                {row.regulator}
              </th>
              <td className="py-2 pr-4 text-text-2">
                {RELEVANCE_LABEL[row.relevance] ?? row.relevance}
              </td>
              <td className="py-2 pr-4">
                {row.checked ? (
                  <span className="inline-flex items-center gap-1 text-ver">
                    <Check size={14} aria-hidden /> Yes
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-text-3">
                    <Minus size={14} aria-hidden /> No
                  </span>
                )}
              </td>
              <td className="py-2 text-text-2">
                <Masked text={row.rationale} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConflictLog({ view }: { view: CaseView }) {
  if (view.conflicts.length === 0) {
    return <p className="text-sm text-text-3">No conflicts arose in this case.</p>;
  }
  return (
    <ol className="flex flex-col gap-2">
      {view.conflicts.map((conflict) => (
        <li key={conflict.id} className="glass-thin p-3 text-sm">
          <p className="flex flex-wrap items-baseline gap-x-2">
            <span className="data text-challenge">{conflict.type}</span>
            <span className="font-medium">{CONFLICT_LABEL[conflict.type]}</span>
            <span className="ml-auto text-xs text-text-3">{conflict.status}</span>
          </p>
          <p className="mt-1 text-text-2">
            <Masked text={conflict.summary} />
          </p>
          {conflict.rule && (
            <p className="mt-1 text-xs text-text-3">
              {conflict.outcome} under rule <span className="data">{conflict.rule}</span>
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

function VerifierReport({ view }: { view: CaseView }) {
  if (view.verdicts.length === 0) {
    return <p className="text-sm text-text-3">The Verifier did not run in this condition.</p>;
  }
  return (
    <ol className="flex flex-col gap-3">
      {view.verdicts.map((verdict) => (
        <li key={verdict.version}>
          <p className="flex items-center gap-2 text-sm font-medium">
            {verdict.decision === "VETO" ? (
              <ShieldAlert size={16} color="var(--color-veto)" aria-hidden />
            ) : (
              <Check size={16} color="var(--color-approve)" aria-hidden />
            )}
            {verdict.decision === "VETO" ? "Vetoed" : "Approved"}, proposal v{verdict.version}
          </p>
          <ul className="mt-1.5 flex flex-wrap gap-1" aria-label="Gates">
            {verdict.gates.map((gate) => (
              <li
                key={gate.gate}
                className={`data rounded border px-1 text-[11px] ${
                  gate.passed ? "border-ver/40 text-ver" : "border-veto/60 text-veto"
                }`}
              >
                {gate.gate} {gate.passed ? "passed" : "failed"}
              </li>
            ))}
          </ul>
          {verdict.reasons.length > 0 && (
            <ul className="mt-1.5 flex flex-col gap-1 text-sm text-text-2">
              {verdict.reasons.map((reason) => (
                <li key={reason}>
                  <Masked text={reason} />
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="glass p-5" aria-label={title}>
      <h2 className="eyebrow mb-3">{title}</h2>
      {children}
    </section>
  );
}

/** The result, with every claim tied to its evidence. Nothing here recommends anything. */
export function Dossier({ id }: { id: string }) {
  const load = useCallback(() => api.report(id), [id]);
  const report = useLoad(load);
  const { events, state } = useCaseEvents(id);
  const view = useMemo(() => fold(events), [events]);

  if (report.error) {
    if (report.error.status === 0) {
      return (
        <div className="mx-auto w-full max-w-3xl px-4 py-10">
          <ApiOffline message={report.error.message} />
        </div>
      );
    }
    return (
      <div className="mx-auto w-full max-w-xl px-4 py-10">
        <Notice title={report.error.status === 409 ? "This case has not finished" : "No such case"}>
          <Link className="underline" href={`/cases/${encodeURIComponent(id)}`}>
            Watch the case
          </Link>
        </Notice>
      </div>
    );
  }
  if (!report.data) return <p className="p-8 text-text-3">Loading the result…</p>;
  const data = report.data;

  return (
    <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-4 px-4 pt-2 pb-10 lg:px-6">
      <div className="flex flex-wrap items-center gap-3" data-print-hide>
        <Link href={`/cases/${encodeURIComponent(id)}?replay=1`} className="button h-9!">
          <ArrowLeft size={15} aria-hidden /> Replay the case
        </Link>
        <span className="data text-sm text-text-2">{data.case_id}</span>
        {data.synthetic && <SyntheticBadge />}
        <span className="text-sm text-text-2">{conditionName(data.condition)}</span>
        <button
          type="button"
          className="button ml-auto h-9!"
          onClick={() => void api.trace(id).then((trace) => saveJson(`${id}-trace.json`, trace))}
          title="The event log, masked as stored. The report itself is not exported."
        >
          <Download size={15} aria-hidden /> Masked trace
        </button>
      </div>

      <ResultHero report={data} />

      <Panel title="What the records say">
        <Claims report={data} />
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Regulators">
          <Coverage report={data} />
        </Panel>
        <div className="flex flex-col gap-4">
          <Panel title="Sources">
            <ul className="flex flex-col gap-1 text-sm">
              {data.sources.map((source) => (
                <li key={source.source} className="flex justify-between gap-4">
                  <span className="text-text-2">{source.source}</span>
                  <span className="data text-text-3">{source.as_of ?? "undated"}</span>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Check it yourself">
            <ul className="flex flex-col gap-1 text-sm">
              {data.how_to_verify.map((item) => (
                <li key={item.regulator}>
                  <a
                    href={item.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-inform hover:underline"
                  >
                    {item.regulator} official site <ExternalLink size={12} aria-hidden />
                  </a>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>

      {state !== "failed" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Conflict log">
            <ConflictLog view={view} />
          </Panel>
          <Panel title="Verifier report">
            <VerifierReport view={view} />
          </Panel>
        </div>
      )}

      <p className="glass-thin p-4 text-sm leading-relaxed text-text-2" data-testid="disclaimer">
        {data.disclaimer}
      </p>
    </div>
  );
}
