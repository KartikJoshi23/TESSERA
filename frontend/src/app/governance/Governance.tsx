"use client";

import { Database, EyeOff, Link2Off, Lock, type LucideIcon, ScanLine, ShieldCheck } from "lucide-react";
import { ApiOffline, PageTitle } from "@/components/ui";
import type { Source } from "@/lib/api";
import { useStatus } from "@/lib/hooks";

const ACCESS_LABEL: Record<string, string> = {
  manual_export: "Manual export only",
  manual_download: "Manual download only",
  hand_record: "Recorded by hand",
  api: "Public API",
};

function Badge({ icon: Icon, children, tone }: { icon: LucideIcon; children: string; tone?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-line-strong px-1.5 py-0.5 text-[11px] whitespace-nowrap text-text-2"
      style={tone ? { borderColor: tone, color: tone } : undefined}
    >
      <Icon size={12} aria-hidden />
      {children}
    </span>
  );
}

function SourceCard({ source }: { source: Source }) {
  return (
    <li className="glass flex flex-col gap-3 p-4" data-testid="source-card">
      <div>
        <p className="eyebrow">{source.regulator}</p>
        <h3 className="mt-1 font-medium">{source.name}</h3>
      </div>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-xs text-text-3">Snapshot</dt>
          <dd className="data">{source.as_of ?? "none yet"}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-3">Records</dt>
          <dd className="data">{source.rows.toLocaleString("en")}</dd>
        </div>
      </dl>
      <div className="mt-auto flex flex-wrap gap-1">
        <Badge icon={ScanLine}>{ACCESS_LABEL[source.access_method] ?? source.access_method}</Badge>
        {!source.automated_access && <Badge icon={ShieldCheck}>No automated access</Badge>}
        {!source.deep_links_allowed && <Badge icon={Link2Off}>Homepage links only</Badge>}
        {source.restricted && (
          <Badge icon={Lock} tone="var(--color-jur)">
            Restricted
          </Badge>
        )}
      </div>
    </li>
  );
}

const MODES = [
  {
    id: "RESEARCH_INTERNAL",
    title: "Research-internal",
    text: "Hand-recorded DFSA facts may be used on this machine, for evaluation only. They are masked before any model call, and dates and names appear only in a report built on request.",
  },
  {
    id: "RESTRICTED_DEMO",
    title: "Restricted demo",
    text: "No DFSA material is loaded at all. The system says the DFSA could not be checked, and links to its homepage.",
  },
];

/** What the system may read, how it got it, and what leaves the machine. */
export function Governance() {
  const { data, error } = useStatus();
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 py-6 lg:px-6">
      <PageTitle eyebrow="Data and governance" title="What the system may read">
        Each source has its own rules. They live in a policy file and are enforced in code, not only
        written down here.
      </PageTitle>

      {error && <ApiOffline message={error.message} />}

      <section aria-labelledby="restricted" className="glass border-jur/30! p-5">
        <h2 id="restricted" className="flex items-center gap-2 font-medium text-jur">
          <Lock size={16} aria-hidden /> DFSA material
        </h2>
        <p className="mt-2 max-w-4xl text-sm leading-relaxed text-text-2">
          The DFSA&apos;s legal disclaimer bars storing its material in any public or private
          electronic retrieval system, bars caching, and bars any deep link other than to its
          homepage. Facts are recorded by hand for internal research evaluation, and never appear in
          a public tool without written permission. DFSA pages are never fetched, and every link
          this interface shows to the DFSA is to its homepage. API responses are marked
          &quot;no-store&quot;, so a browser keeps no copy of a report.
        </p>
      </section>

      {data && (
        <>
          <section aria-labelledby="sources">
            <h2 id="sources" className="eyebrow mb-3">
              Sources in use
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.sources.map((source) => (
                <SourceCard key={source.source_id} source={source} />
              ))}
            </ul>
          </section>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <section className="glass p-5" aria-labelledby="modes">
              <h2 id="modes" className="eyebrow mb-3">
                Modes
              </h2>
              <ul className="flex flex-col gap-3">
                {MODES.map((mode) => (
                  <li key={mode.id} className="flex gap-3">
                    <span
                      aria-hidden
                      className={`mt-1.5 size-2.5 shrink-0 rotate-45 rounded-[2px] ${data.mode === mode.id ? "bg-cma" : "bg-white/15"}`}
                    />
                    <div>
                      <p className="text-sm font-medium">
                        {mode.title}
                        {data.mode === mode.id && <span className="ml-2 text-xs text-cma">in use</span>}
                      </p>
                      <p className="mt-0.5 text-sm leading-relaxed text-text-2">{mode.text}</p>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="mt-4 text-xs text-text-3">
                The mode is set when the API starts. This page cannot change it.
              </p>
            </section>

            <section className="glass flex flex-col gap-3 p-5" aria-labelledby="masking">
              <h2 id="masking" className="eyebrow">
                Masking
              </h2>
              <p className="flex items-baseline gap-2">
                <span className="display text-4xl" data-testid="masked-values">
                  {data.masked_values}
                </span>
                <span className="text-sm text-text-2">values masked since the API started</span>
              </p>
              <p className="flex items-start gap-2 text-sm leading-relaxed text-text-2">
                <EyeOff size={15} aria-hidden className="mt-0.5 shrink-0" />
                Models see placeholders only. Every request is checked for a leak before it leaves
                this machine.
              </p>
              <p className="flex items-start gap-2 text-sm leading-relaxed text-text-2">
                <Database size={15} aria-hidden className="mt-0.5 shrink-0" />
                The event log holds the masked form, and is what you see in the Theater.
              </p>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
