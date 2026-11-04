"use client";

import { motion } from "motion/react";
import { useMemo } from "react";
import type { Conflict, Finding } from "@/lib/reducer";
import { agentLook, CONFLICT_LABEL, describeAssertion } from "@/lib/vocabulary";
import { anchorOf, CENTRE, hexPoints, layoutTiles, type Point, TILE_RADIUS } from "./geometry";

const TILE = hexPoints(TILE_RADIUS);
const SETTLE = { type: "spring", stiffness: 85, damping: 15, mass: 0.9 } as const;
const LABEL_OFFSET = 24;

interface TileProps {
  finding: Finding;
  slot: Point;
  /** Set once there is a result: true if the result rests on this finding. */
  cited: boolean | null;
  selected: boolean;
  still: boolean;
  onSelect: (id: string) => void;
}

function Tile({ finding, slot, cited, selected, still, onSelect }: TileProps) {
  const look = agentLook(finding.author);
  const from = anchorOf(finding.author);
  const gone = finding.status === "superseded" || finding.status === "withdrawn";
  const challenged = finding.status === "challenged";
  const strength = cited === null ? 0.55 : cited ? 0.9 : 0.16;
  return (
    <motion.g
      data-testid="finding-tile"
      data-finding={finding.id}
      initial={
        still
          ? { x: slot.x, y: slot.y, opacity: 0 }
          : { x: from.x, y: from.y, opacity: 0, scale: 0.35 }
      }
      animate={{ x: slot.x, y: slot.y, opacity: gone ? 0.3 : 1, scale: 1 }}
      transition={still ? { duration: 0.2 } : SETTLE}
      className="cursor-pointer"
      onClick={() => onSelect(finding.id)}
    >
      <title>{`${finding.id} · ${look.name}. ${describeAssertion(finding.assertion)}`}</title>
      <polygon
        points={TILE}
        fill={look.color}
        fillOpacity={strength}
        stroke={challenged ? "var(--color-challenge)" : selected ? "var(--color-text)" : look.color}
        strokeOpacity={challenged || selected ? 1 : cited === false ? 0.35 : 0.9}
        strokeWidth={challenged || selected ? 2 : 1}
        strokeDasharray={gone ? "3 3" : undefined}
      />
      {finding.version > 1 && <circle r={3} fill="var(--color-revise)" />}
    </motion.g>
  );
}

const LINK_COLOR: Record<string, string> = {
  open: "var(--color-challenge)",
  resolved: "var(--color-resolve)",
  unresolved: "var(--color-rebut)",
  settled: "var(--color-concede)",
};

function ConflictLink({ conflict, slots }: { conflict: Conflict; slots: Map<string, Point> }) {
  const placed = conflict.findingIds.flatMap((id) => slots.get(id) ?? []);
  const [a, b] = placed;
  if (!a) return null;
  const end = b ?? { x: a.x + 18, y: a.y - 18 };
  const color = LINK_COLOR[conflict.status] ?? LINK_COLOR.open;
  // The label sits outside the mosaic, by the first finding, where nothing else is drawn.
  const reach = Math.hypot(a.x - CENTRE.x, a.y - CENTRE.y) || 1;
  const label = {
    x: a.x + ((a.x - CENTRE.x) / reach) * LABEL_OFFSET,
    y: a.y + ((a.y - CENTRE.y) / reach) * LABEL_OFFSET,
  };
  return (
    <g pointerEvents="none" data-testid="conflict-link" data-status={conflict.status}>
      <motion.line
        x1={a.x}
        y1={a.y}
        x2={end.x}
        y2={end.y}
        stroke={color}
        strokeWidth={conflict.status === "open" ? 2 : 1.2}
        strokeOpacity={conflict.status === "settled" ? 0.5 : 0.9}
        strokeDasharray={conflict.status === "open" ? undefined : "4 3"}
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.5 }}
      />
      <g transform={`translate(${label.x} ${label.y})`}>
        <rect x={-11} y={-8} width={22} height={16} rx={4} fill="var(--color-lapis-900)" stroke={color} />
        <text textAnchor="middle" y={4} fontSize={10} fill={color} className="data">
          {conflict.type}
        </text>
        <title>{CONFLICT_LABEL[conflict.type] ?? conflict.type}</title>
      </g>
    </g>
  );
}

interface Props {
  findings: Finding[];
  conflicts: Conflict[];
  citedIds: string[] | null;
  selected: string | null;
  still: boolean;
  onSelect: (id: string) => void;
}

export function TileMosaic({ findings, conflicts, citedIds, selected, still, onSelect }: Props) {
  const slots = useMemo(() => layoutTiles(findings), [findings]);
  // A result that cites nothing has no findings to pick out, so all of them stay lit.
  const cited = citedIds?.length ? new Set(citedIds) : null;
  return (
    <g>
      {findings.map((finding) => {
        const slot = slots.get(finding.id);
        if (!slot) return null;
        return (
          <Tile
            key={finding.id}
            finding={finding}
            slot={slot}
            cited={cited ? cited.has(finding.id) : null}
            selected={selected === finding.id}
            still={still}
            onSelect={onSelect}
          />
        );
      })}
      {conflicts.map((conflict) => (
        <ConflictLink key={conflict.id} conflict={conflict} slots={slots} />
      ))}
    </g>
  );
}
