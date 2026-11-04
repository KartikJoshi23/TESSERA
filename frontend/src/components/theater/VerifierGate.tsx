"use client";

import { AnimatePresence, motion } from "motion/react";
import type { Gate, Proposal, Verdict } from "@/lib/reducer";
import { RESULT_LOOK } from "@/lib/vocabulary";
import { GATE_X, PATH_Y, RESULT_X } from "./geometry";

const DOOR_WIDTH = 44;
const DOOR_HEIGHT = 112;
const GAP = 3;
const GATE_IDS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"];
const DOOR_TRAVEL = 34;
/** Far enough out that the doors clear both when they open. */
const LABEL_Y = PATH_Y - GAP - DOOR_HEIGHT - DOOR_TRAVEL - 12;
const READING_Y = PATH_Y + GAP + DOOR_HEIGHT + DOOR_TRAVEL + 20;

function Light({ id, gate, x, y }: { id: string; gate: Gate | undefined; x: number; y: number }) {
  const color = !gate
    ? "var(--color-lapis-700)"
    : gate.passed
      ? "var(--color-ver)"
      : "var(--color-veto)";
  return (
    <g transform={`translate(${x} ${y})`} data-testid={`gate-${id}`} data-passed={gate?.passed}>
      <title>{`${id}${gate ? (gate.passed ? " passed" : ` failed: ${gate.detail}`) : ""}`}</title>
      {gate && !gate.passed && <circle r={9} fill={color} opacity={0.3} />}
      <circle r={4.5} fill={color} stroke="var(--color-line-strong)" strokeWidth={0.75} />
      <text x={9} y={3.5} fontSize={9.5} fill="var(--color-text-3)" className="data">
        {id}
      </text>
    </g>
  );
}

type Stance = "shut" | "veto" | "open";

function Door({
  side,
  stance,
  gates,
  ids,
}: {
  side: "top" | "bottom";
  stance: Stance;
  gates: Gate[];
  ids: string[];
}) {
  const direction = side === "top" ? -1 : 1;
  const y = side === "top" ? PATH_Y - GAP - DOOR_HEIGHT : PATH_Y + GAP;
  const stroke =
    stance === "veto"
      ? "var(--color-veto)"
      : stance === "open"
        ? "var(--color-ver)"
        : "var(--color-line-strong)";
  return (
    <motion.g
      animate={{ y: stance === "open" ? direction * DOOR_TRAVEL : 0 }}
      transition={{ type: "spring", stiffness: 70, damping: 14 }}
    >
      <rect
        x={GATE_X - DOOR_WIDTH / 2}
        y={y}
        width={DOOR_WIDTH}
        height={DOOR_HEIGHT}
        rx={9}
        fill="var(--color-lapis-800)"
        fillOpacity={0.85}
        stroke={stroke}
        strokeWidth={1.3}
      />
      {ids.map((id, index) => (
        <Light
          key={id}
          id={id}
          gate={gates.find((gate) => gate.gate === id)}
          x={GATE_X - 12}
          y={y + 20 + index * 24}
        />
      ))}
    </motion.g>
  );
}

interface Props {
  enabled: boolean;
  working: boolean;
  proposal: Proposal | null;
  verdict: Verdict | null;
  vetoes: number;
  still: boolean;
  onSelect?: () => void;
}

/** The only way to the result. A proposal waits here, and a veto sends it back. */
export function VerifierGate({
  enabled,
  working,
  proposal,
  verdict,
  vetoes,
  still,
  onSelect,
}: Props) {
  const current = verdict && proposal && verdict.version === proposal.version ? verdict : null;
  const stance: Stance = !enabled
    ? "open"
    : current?.decision === "APPROVE"
      ? "open"
      : current?.decision === "VETO"
        ? "veto"
        : "shut";
  const gates = verdict?.gates ?? [];
  const look = proposal ? RESULT_LOOK[proposal.result] : undefined;
  const reading = !current
    ? null
    : current.decision === "APPROVE"
      ? "every claim supported"
      : current.contradictions.length
        ? `${current.contradictions.length} contradicted by evidence`
        : current.underCall
          ? "result understated"
          : `failed ${gates.filter((gate) => !gate.passed).length} of ${gates.length} gates`;

  // Where the proposal stands: at the gate, sent back, or through to the result.
  const tileX = !proposal
    ? 0
    : stance === "open"
      ? RESULT_X - 74
      : stance === "veto"
        ? GATE_X - 150
        : GATE_X - 58;

  return (
    <g data-testid="verifier-gate" data-stance={stance}>
      <g
        role="button"
        tabIndex={0}
        aria-label={`Verifier gate: ${stance === "shut" ? "closed" : stance === "open" ? "open" : "vetoed"}`}
        className="cursor-pointer"
        onClick={onSelect}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect?.();
          }
        }}
      >
        <rect
          className="focus-ring"
          x={GATE_X - 44}
          y={LABEL_Y - 18}
          width={88}
          height={26}
          rx={6}
          fill="transparent"
          stroke="transparent"
        />
        <text
          x={GATE_X}
          y={LABEL_Y}
          textAnchor="middle"
          fontSize={14}
          fontWeight={600}
          fill={working ? "var(--color-ver)" : "var(--color-text)"}
          className={working ? "tile-breathe" : undefined}
        >
          Verifier
        </text>
      </g>
      {!enabled && (
        <text x={GATE_X} y={READING_Y} textAnchor="middle" fontSize={11} fill="var(--color-text-3)" className="data">
          off in this condition
        </text>
      )}
      {reading && (
        <text
          x={GATE_X}
          y={READING_Y}
          textAnchor="middle"
          fontSize={11}
          fill={stance === "veto" ? "var(--color-veto)" : "var(--color-ver)"}
          className="data"
        >
          {reading}
        </text>
      )}
      {enabled ? (
        <>
          <Door side="top" stance={stance} gates={gates} ids={GATE_IDS.slice(0, 4)} />
          <Door side="bottom" stance={stance} gates={gates} ids={GATE_IDS.slice(4)} />
        </>
      ) : (
        <path
          d={`M ${GATE_X} ${PATH_Y - 115} V ${PATH_Y - 40} M ${GATE_X} ${PATH_Y + 40} V ${PATH_Y + 115}`}
          stroke="var(--color-line-strong)"
          strokeDasharray="4 6"
        />
      )}

      {proposal && (
        <motion.g
          data-testid="proposal-tile"
          initial={{ x: GATE_X - 210, y: PATH_Y, opacity: 0 }}
          animate={{
            x: tileX,
            y: PATH_Y,
            opacity: stance === "open" ? 0 : stance === "veto" ? 0.75 : 1,
          }}
          transition={
            still ? { duration: 0.2 } : { type: "spring", stiffness: 60, damping: 14, mass: 1.2 }
          }
        >
          <rect
            x={-35}
            y={-23}
            width={70}
            height={46}
            rx={9}
            fill="var(--color-lapis-800)"
            stroke={look?.color ?? "var(--color-text-3)"}
            strokeWidth={1.4}
          />
          <text x={-8} textAnchor="middle" y={-3} fontSize={10} fill="var(--color-text-2)">
            proposal
          </text>
          <text x={-8} textAnchor="middle" y={13} fontSize={13} fontWeight={600} fill={look?.color} className="data">
            v{proposal.version}
          </text>
          {stance === "veto" && (
            <polyline
              points="24,-23 16,-10 26,0 15,10 22,23"
              fill="none"
              stroke="var(--color-veto)"
              strokeWidth={1.8}
              data-testid="proposal-crack"
            />
          )}
        </motion.g>
      )}

      <AnimatePresence>
        {stance === "veto" && !still && (
          <motion.g
            key={`veto-${vetoes}`}
            initial={{ opacity: 0, scale: 0.4, x: GATE_X, y: PATH_Y }}
            animate={{ opacity: [0, 1, 1, 0], scale: [0.4, 1.25, 1, 1], x: GATE_X, y: PATH_Y }}
            transition={{ duration: 1.3, times: [0, 0.2, 0.7, 1] }}
          >
            <path
              d="M0 -32 L27 -21 V4 C27 21 13 30 0 36 C-13 30 -27 21 -27 4 V-21 Z"
              fill="var(--color-veto)"
              fillOpacity={0.2}
              stroke="var(--color-veto)"
              strokeWidth={2}
            />
            <path d="M-11 -11 L11 11 M11 -11 L-11 11" stroke="var(--color-veto)" strokeWidth={4} strokeLinecap="round" />
          </motion.g>
        )}
      </AnimatePresence>
    </g>
  );
}
