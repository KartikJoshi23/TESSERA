"use client";

import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useId, useMemo } from "react";
import { RESULT_ICON } from "@/components/ResultMark";
import type { AgentKey, CaseView } from "@/lib/reducer";
import { agentLook, hasVerifier, isCrew, resultLook } from "@/lib/vocabulary";
import { AgentNode } from "./AgentNode";
import {
  arcPath,
  cameraOn,
  CENTRE,
  hexPoints,
  NODE,
  PATH_Y,
  type Point,
  RESULT_X,
  STAGE,
} from "./geometry";
import { Particles, useParticles } from "./Particles";
import { TileMosaic } from "./TileMosaic";
import { VerifierGate } from "./VerifierGate";

const CREW: AgentKey[] = ["JUR", "CMA", "DFSA", "VARA", "CLN", "REC"];
const LINKS: [AgentKey, AgentKey][] = [
  ["JUR", "CMA"],
  ["JUR", "VARA"],
  ["JUR", "DFSA"],
  ["CMA", "DFSA"],
  ["DFSA", "VARA"],
  ["CMA", "REC"],
  ["VARA", "REC"],
  ["CLN", "REC"],
  ["CMA", "CLN"],
  ["VARA", "CLN"],
];

const WIDE_VIEW = `0 0 ${STAGE.width} ${STAGE.height}`;

function ResultSlot({ view, href }: { view: CaseView; href?: string }) {
  const result = view.final?.result ?? null;
  const look = resultLook(result);
  const Icon = result ? RESULT_ICON[result] : null;
  const body = (
    <g transform={`translate(${RESULT_X} ${PATH_Y})`} data-testid="result-tile" data-result={result ?? ""}>
      <rect
        x={-74}
        y={-96}
        width={148}
        height={192}
        rx={18}
        fill={look ? look.color : "transparent"}
        fillOpacity={look ? 0.1 : 0}
        stroke={look ? look.color : "var(--color-line-strong)"}
        strokeWidth={look ? 1.6 : 1}
        strokeDasharray={look ? undefined : "5 6"}
      />
      {look && Icon ? (
        <>
          <Icon x={-24} y={-70} width={48} height={48} color={look.color} strokeWidth={1.4} />
          <foreignObject x={-68} y={-10} width={136} height={92}>
            <p
              className="px-1 text-center text-[15px] leading-snug font-semibold"
              style={{ color: look.color }}
            >
              {look.label}
            </p>
          </foreignObject>
        </>
      ) : (
        <text textAnchor="middle" y={5} fontSize={13} fill="var(--color-text-3)">
          {view.ended && view.ended !== "finished" ? "No result" : "Awaiting result"}
        </text>
      )}
    </g>
  );
  return href && look ? (
    <Link href={href} aria-label={`Open the result: ${look.label}`}>
      {body}
    </Link>
  ) : (
    body
  );
}

interface Props {
  view: CaseView;
  speed?: number;
  presenter?: boolean;
  compact?: boolean;
  selectedAgent?: string | null;
  selectedFinding?: string | null;
  resultHref?: string;
  onSelectAgent?: (agent: AgentKey) => void;
  onSelectFinding?: (id: string) => void;
  onSelectMessage?: (id: string) => void;
  onSelectVerifier?: () => void;
}

/**
 * The signature view. Each agent is a glass tile. Each finding flies from its agent into the mosaic
 * round the Reconciler, and the Verifier is a gate on the only path to the result. Everything drawn
 * comes from the case's event log, so nothing here is decoration.
 */
export function Stage({
  view,
  speed = 1,
  presenter = false,
  compact = false,
  selectedAgent = null,
  selectedFinding = null,
  resultHref,
  onSelectAgent,
  onSelectFinding,
  onSelectMessage,
  onSelectVerifier,
}: Props) {
  const reduced = useReducedMotion() ?? false;
  const { flying, land } = useParticles(view.messages, reduced);
  const base = useId().replace(/[^a-zA-Z0-9]/g, "");
  const ids = { glass: `${base}glass`, halo: `${base}halo`, glow: `${base}glow`, light: `${base}light` };
  const crew = isCrew(view.condition);
  const agents = crew ? CREW : (["SA"] as AgentKey[]);
  const veto = hasVerifier(view.condition);
  const proposal = view.proposals.at(-1) ?? null;
  const verdict = view.verdicts.at(-1) ?? null;
  const vetoes = view.verdicts.filter((item) => item.decision === "VETO").length;
  const camera: Point | null = presenter && !reduced && view.active ? NODE[view.active] : null;
  const viewBox = camera ? cameraOn(camera) : WIDE_VIEW;
  const links = useMemo(
    () => (crew ? LINKS.map(([a, b]) => arcPath(NODE[a], NODE[b], 0.06)) : []),
    [crew],
  );

  return (
    <motion.svg
      className="stage absolute inset-0 h-full w-full"
      viewBox={WIDE_VIEW}
      animate={{ viewBox }}
      transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      role="group"
      aria-label="The crew at work. The same events are listed in the blackboard."
    >
      <defs>
        <linearGradient id={ids.glass} x1="0" y1="0" x2="0.6" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.14" />
          <stop offset="0.55" stopColor="#7dd3fc" stopOpacity="0.05" />
          <stop offset="1" stopColor="#0a0f1c" stopOpacity="0.85" />
        </linearGradient>
        <radialGradient id={ids.light}>
          <stop offset="0" stopColor="#7dd3fc" stopOpacity="0.14" />
          <stop offset="0.6" stopColor="#7dd3fc" stopOpacity="0.03" />
          <stop offset="1" stopColor="#7dd3fc" stopOpacity="0" />
        </radialGradient>
        <filter id={ids.halo} x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="13" />
        </filter>
        <filter id={ids.glow} x="-120%" y="-120%" width="340%" height="340%">
          <feGaussianBlur stdDeviation="2.4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <circle cx={CENTRE.x} cy={CENTRE.y} r={190} fill={`url(#${ids.light})`} />

      {links.map((path) => (
        <path key={path} d={path} fill="none" stroke="var(--color-line)" strokeWidth={1} />
      ))}
      {/* The only path to the result. */}
      <path
        d={`M ${CENTRE.x + 42} ${PATH_Y} H ${RESULT_X - 74}`}
        fill="none"
        stroke="var(--color-line-strong)"
        strokeWidth={1.5}
        strokeDasharray="2 6"
      />

      <TileMosaic
        findings={view.findings}
        conflicts={view.conflicts}
        citedIds={view.final ? view.final.findingIds : null}
        selected={selectedFinding}
        still={reduced}
        onSelect={(id) => onSelectFinding?.(id)}
      />

      {agents.map((agent) => (
        <AgentNode
          key={agent}
          agent={agent}
          look={agentLook(agent, view.condition)}
          state={view.agents[agent]}
          selected={selectedAgent === agent}
          compact={compact}
          gradient={ids.glass}
          halo={ids.halo}
          onSelect={(key) => onSelectAgent?.(key)}
        />
      ))}

      {!crew && (
        <polygon
          points={hexPoints(26)}
          transform={`translate(${CENTRE.x} ${CENTRE.y})`}
          fill="none"
          stroke="var(--color-line-strong)"
          strokeDasharray="3 5"
        />
      )}

      <VerifierGate
        enabled={veto}
        working={view.agents.VER.status === "thinking" || view.agents.VER.status === "tool"}
        proposal={proposal}
        verdict={verdict}
        vetoes={vetoes}
        still={reduced}
        onSelect={onSelectVerifier}
      />
      <ResultSlot view={view} href={resultHref} />

      <Particles
        flying={flying}
        speed={speed}
        glow={ids.glow}
        onLand={land}
        onSelect={(id) => onSelectMessage?.(id)}
      />
    </motion.svg>
  );
}
