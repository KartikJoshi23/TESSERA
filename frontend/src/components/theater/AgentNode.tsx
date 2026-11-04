"use client";

import {
  Bot,
  Building2,
  Coins,
  Compass,
  Contact,
  Landmark,
  type LucideIcon,
  Scale,
  ShieldCheck,
} from "lucide-react";
import type { AgentKey, AgentState } from "@/lib/reducer";
import { type AgentLook } from "@/lib/vocabulary";
import { hexPoints, NODE } from "./geometry";

const ICON: Record<AgentKey, LucideIcon> = {
  JUR: Compass,
  CMA: Landmark,
  DFSA: Building2,
  VARA: Coins,
  CLN: Contact,
  REC: Scale,
  VER: ShieldCheck,
  SA: Bot,
};

const STATUS_WORD: Record<AgentState["status"], string> = {
  idle: "idle",
  thinking: "thinking",
  tool: "reading a record",
  done: "finished",
  failed: "could not finish",
};

const RADIUS = 36;
/** The Reconciler sits inside the mosaic, so its name goes on the tile itself. */
const CENTRE_RADIUS = 48;

/** A label beside the tile, for tiles with something directly below them. */
const SIDE_LABEL: Partial<Record<AgentKey, boolean>> = { JUR: true, DFSA: true, CLN: true };

interface Props {
  agent: AgentKey;
  look: AgentLook;
  state: AgentState;
  selected: boolean;
  compact: boolean;
  gradient: string;
  halo: string;
  onSelect: (agent: AgentKey) => void;
}

export function AgentNode({
  agent,
  look,
  state,
  selected,
  compact,
  gradient,
  halo,
  onSelect,
}: Props) {
  const { x, y } = NODE[agent];
  const Icon = ICON[agent];
  const working = state.status === "thinking" || state.status === "tool";
  const lit = state.status !== "idle";
  const failed = state.status === "failed";
  const centre = agent === "REC";
  const radius = centre ? CENTRE_RADIUS : RADIUS;
  const core = hexPoints(radius);
  const ring = hexPoints(radius + 6);
  const iconSize = centre ? 26 : 24;
  const iconY = centre ? -24 : -12;
  const side = SIDE_LABEL[agent] ?? false;
  const labelX = side ? radius + 14 : 0;
  const labelY = centre ? 16 : side ? -2 : radius + 22;
  const detail = state.tool ?? (working ? "thinking" : state.requests ? `${state.requests} req` : "");

  return (
    <g
      transform={`translate(${x} ${y})`}
      role="button"
      tabIndex={0}
      aria-label={`${look.name}: ${STATUS_WORD[state.status]}${state.challenged ? ", challenged" : ""}`}
      aria-pressed={selected}
      className="cursor-pointer"
      onClick={() => onSelect(agent)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(agent);
        }
      }}
    >
      <title>{`${look.name}. ${look.role}`}</title>
      <polygon
        points={ring}
        fill={look.color}
        opacity={working ? 0.55 : lit ? 0.16 : 0}
        filter={`url(#${halo})`}
        className={working ? "tile-breathe" : undefined}
      />
      {/* Solid under the glass, so nothing behind a tile shows through it. */}
      <polygon points={core} fill="var(--color-lapis-900)" />
      <polygon
        points={core}
        fill={`url(#${gradient})`}
        stroke={lit ? look.color : "var(--color-line-strong)"}
        strokeOpacity={lit ? 0.85 : 1}
        strokeWidth={1.4}
      />
      <polygon className="focus-ring" points={ring} fill="none" stroke="transparent" />
      {selected && (
        <polygon points={ring} fill="none" stroke={look.color} strokeWidth={1.5} strokeDasharray="2 4" />
      )}
      {state.challenged && (
        <polygon
          points={ring}
          fill="none"
          stroke="var(--color-challenge)"
          strokeWidth={2.2}
          data-testid={`challenged-${agent}`}
        />
      )}
      {failed && (
        <polygon
          points={ring}
          fill="none"
          stroke="var(--color-text-3)"
          strokeWidth={2}
          strokeDasharray="5 4"
        />
      )}
      <Icon
        x={-iconSize / 2}
        y={iconY}
        width={iconSize}
        height={iconSize}
        strokeWidth={1.6}
        color={lit ? look.color : "var(--color-text-3)"}
      />
      {state.status === "tool" && (
        <g className="satellite">
          <circle cx={radius + 12} cy={0} r={4.5} fill={look.color} />
          <circle cx={radius + 12} cy={0} r={8} fill={look.color} opacity={0.25} />
        </g>
      )}
      {state.version > 1 && (
        <g transform={`translate(${radius - 8} ${-radius + 8})`}>
          <rect x={-13} y={-9} width={26} height={18} rx={6} fill="var(--color-lapis-800)" stroke="var(--color-revise)" />
          <text textAnchor="middle" y={4} fontSize={11} fill="var(--color-revise)" className="data">
            v{state.version}
          </text>
        </g>
      )}
      <text
        x={labelX}
        y={labelY}
        textAnchor={side ? "start" : "middle"}
        fontSize={centre ? 12.5 : compact ? 19 : 14}
        fontWeight={600}
        fill={lit ? "var(--color-text)" : "var(--color-text-2)"}
      >
        {look.name}
      </text>
      {!compact && (
        <text
          x={labelX}
          y={labelY + (centre ? 14 : 16)}
          textAnchor={side ? "start" : "middle"}
          fontSize={centre ? 10 : 11}
          fill="var(--color-text-3)"
          className="data"
        >
          {detail}
        </text>
      )}
      {!compact && state.source && state.status === "tool" && (
        <text
          x={labelX}
          y={labelY + 30}
          textAnchor={side ? "start" : "middle"}
          fontSize={10}
          fill={look.color}
          className="data"
        >
          {state.source}
        </text>
      )}
    </g>
  );
}
