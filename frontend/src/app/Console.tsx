"use client";

import { ArrowRight, Play } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useSyncExternalStore } from "react";
import { ResultBadge } from "@/components/ResultMark";
import { hexPoints, hexRing } from "@/components/theater/geometry";
import { ApiOffline } from "@/components/ui";
import { api, type CaseSummary } from "@/lib/api";
import { useLoad, useStatus } from "@/lib/hooks";
import { conditionName } from "@/lib/vocabulary";

/** The name means a mosaic tile: this is the crew's colours settling into place. */
const TILE_COLORS = [
  "var(--color-jur)",
  "var(--color-cma)",
  "var(--color-dfsa)",
  "var(--color-vara)",
  "var(--color-cln)",
  "var(--color-ver)",
];
const HERO_RINGS = [1, 2, 3];
const HERO_RADIUS = 24;
const HERO_SPACING = HERO_RADIUS * Math.sqrt(3) + 4;
const HERO_TILE = hexPoints(HERO_RADIUS);

function heroTiles() {
  const tiles = [{ x: 0, y: 0, ring: 0, color: "var(--color-rec)", index: 0 }];
  for (const ring of HERO_RINGS) {
    for (const { x, y, side } of hexRing(ring, HERO_SPACING)) {
      const color = TILE_COLORS[side] ?? "var(--color-cma)";
      tiles.push({ x, y, ring, color, index: tiles.length });
    }
  }
  return tiles;
}

const TILES = heroTiles();

const nothingToWatch = () => () => undefined;

function HeroMosaic() {
  const reduced = useReducedMotion();
  // The server cannot know someone's motion setting, so the tiles are drawn only in the browser.
  const inBrowser = useSyncExternalStore(
    nothingToWatch,
    () => true,
    () => false,
  );
  return (
    <svg viewBox="-190 -180 380 360" className="h-auto w-full max-w-md" aria-hidden>
      {inBrowser &&
        TILES.map((tile) => (
        <motion.g
          key={tile.index}
          initial={
            reduced
              ? { x: tile.x, y: tile.y, opacity: 1 }
              : { x: tile.x * 2.2, y: tile.y * 2.2, opacity: 0, scale: 0.4 }
          }
          animate={{ x: tile.x, y: tile.y, opacity: 1, scale: 1 }}
          transition={{
            type: "spring",
            stiffness: 60,
            damping: 15,
            delay: reduced ? 0 : tile.ring * 0.14 + (tile.index % 7) * 0.03,
          }}
        >
          <polygon
            points={HERO_TILE}
            fill={tile.color}
            fillOpacity={0.2 + (3 - tile.ring) * 0.16}
            stroke={tile.color}
            strokeOpacity={0.75}
          />
        </motion.g>
        ))}
    </svg>
  );
}

function CaseRow({ item }: { item: CaseSummary }) {
  const href = `/cases/${encodeURIComponent(item.case_id)}`;
  return (
    <tr className="border-t border-line">
      <th scope="row" className="data py-2.5 pr-4 text-sm font-normal">
        <Link href={href} className="hover:underline">
          {item.case_id}
        </Link>
      </th>
      <td className="py-2.5 pr-4 text-sm text-text-2">{conditionName(item.condition)}</td>
      <td className="py-2.5 pr-4">
        {item.running ? (
          <span className="text-sm text-inform">Running</span>
        ) : (
          <ResultBadge result={item.result} />
        )}
      </td>
      <td className="py-2.5 text-right">
        <Link
          href={`${href}?replay=1`}
          aria-label={`Replay ${item.case_id}`}
          className="inline-flex items-center gap-1 text-sm text-text-2 hover:text-text"
        >
          <Play size={13} aria-hidden /> Replay
        </Link>
      </td>
    </tr>
  );
}

const RECENT = 12;

export function Console() {
  const status = useStatus();
  const cases = useLoad(api.cases);
  const recent = [...(cases.data ?? [])].reverse().slice(0, RECENT);
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-8 px-4 pb-10 lg:px-6">
      <section className="grid items-center gap-6 py-4 lg:grid-cols-[minmax(0,1fr)_26rem] lg:py-10">
        <div>
          <p className="eyebrow">Multi-agent research prototype</p>
          <h1 className="display mt-4 text-4xl leading-[1.15] sm:text-5xl">
            Does this offer match the official record?
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-text-2">
            A crew of agents works out which UAE regulators are relevant, checks their registers and
            alert lists, compares contact details, and argues it out on a shared board. A Verifier
            can veto any conclusion the evidence does not support.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link href="/intake" className="button button-primary h-11! px-5!">
              Start a case <ArrowRight size={16} aria-hidden />
            </Link>
            <Link href="/arena" className="button h-11! px-5!">
              Crew against single agent
            </Link>
          </div>
        </div>
        <div className="flex justify-center">
          <HeroMosaic />
        </div>
      </section>

      {status.error && <ApiOffline message={status.error.message} />}

      {status.data && (
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="System">
          {[
            ["Model", status.data.model.split("/").at(-1) ?? ""],
            ["Regulators checked", status.data.covered_regulators.join(", ") || "None"],
            ["Sources loaded", String(status.data.sources.length)],
            ["Model calls", status.data.model_ready ? "Ready" : "No key set"],
          ].map(([label, value]) => (
            <div key={label} className="glass px-4 py-3">
              <dt className="eyebrow">{label}</dt>
              <dd className="data mt-1 truncate text-sm" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {cases.data && (
        <section className="glass p-5" aria-labelledby="recent">
          <h2 id="recent" className="eyebrow mb-2">
            Recent cases
          </h2>
          {recent.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <caption className="sr-only">The most recent cases, newest first</caption>
                <thead className="sr-only">
                  <tr>
                    <th scope="col">Case</th>
                    <th scope="col">System</th>
                    <th scope="col">Result</th>
                    <th scope="col">Replay</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((item) => (
                    <CaseRow key={item.case_id} item={item} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-6 text-center text-sm text-text-3">No cases yet.</p>
          )}
        </section>
      )}
    </div>
  );
}
