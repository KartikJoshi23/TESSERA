/**
 * Where everything sits on the stage. Pure numbers, so the layout can be tested and two stages on
 * one page (the Arena) always match.
 */
import type { AgentKey } from "@/lib/reducer";

export interface Point {
  x: number;
  y: number;
}

export const STAGE = { width: 1000, height: 620 };
export const CENTRE: Point = { x: 400, y: 322 };
export const PATH_Y = CENTRE.y;
export const GATE_X = 770;
export const RESULT_X = 908;

export const NODE: Record<AgentKey, Point> = {
  JUR: { x: 400, y: 50 },
  CMA: { x: 132, y: 214 },
  DFSA: { x: 400, y: 138 },
  VARA: { x: 668, y: 214 },
  CLN: { x: 400, y: 570 },
  REC: CENTRE,
  VER: { x: GATE_X, y: PATH_Y },
  SA: { x: 132, y: PATH_Y },
};

/** Which way each agent's tiles grow from the centre, in degrees. */
const TILE_BEARING: Record<string, number> = {
  JUR: -112,
  DFSA: -68,
  CMA: -168,
  VARA: -12,
  CLN: 90,
  REC: 30,
  VER: 30,
  SA: 180,
  ORC: 150,
};

export function hexPoints(radius: number): string {
  return Array.from({ length: 6 }, (_, index) => {
    const angle = (Math.PI / 180) * (60 * index - 90);
    return `${(radius * Math.cos(angle)).toFixed(2)},${(radius * Math.sin(angle)).toFixed(2)}`;
  }).join(" ");
}

export const TILE_RADIUS = 13;
const TILE_STEP = TILE_RADIUS * Math.sqrt(3) + 2;
const FIRST_RING = 3;
const LAST_RING = 6;
const WEDGE = 2.2;

interface Slot extends Point {
  ring: number;
  bearing: number;
}

const AXIAL_STEPS = [
  [1, 0],
  [0, 1],
  [-1, 1],
  [-1, 0],
  [0, -1],
  [1, -1],
] as const;

/** The places one ring out from a centre tile, for tiles this far apart. */
export function hexRing(radius: number, spacing: number): (Point & { side: number })[] {
  const places: (Point & { side: number })[] = [];
  let q = 0;
  let r = -radius;
  AXIAL_STEPS.forEach(([stepQ, stepR], side) => {
    for (let step = 0; step < radius; step += 1) {
      places.push({ x: spacing * (q + r / 2), y: spacing * (Math.sqrt(3) / 2) * r, side });
      q += stepQ;
      r += stepR;
    }
  });
  return places;
}

function ring(radius: number): Slot[] {
  return hexRing(radius, TILE_STEP).map(({ x, y }) => ({
    x: CENTRE.x + x,
    y: CENTRE.y + y,
    ring: radius,
    bearing: (Math.atan2(y, x) * 180) / Math.PI,
  }));
}

const SLOTS: Slot[] = Array.from({ length: LAST_RING - FIRST_RING + 1 }, (_, index) =>
  ring(FIRST_RING + index),
).flat();

export const TILE_CAPACITY = SLOTS.length;

const turn = (a: number, b: number): number => {
  const difference = Math.abs(a - b) % 360;
  return difference > 180 ? 360 - difference : difference;
};

/**
 * A place for every finding. Each one takes the free slot nearest its author, inner rings first,
 * so each agent's tiles grow as a wedge pointing at that agent. Slots are given in posting order,
 * and a tile keeps its slot as more arrive.
 */
export function layoutTiles(findings: readonly { id: string; author: string }[]): Map<string, Point> {
  const free = [...SLOTS];
  const placed = new Map<string, Point>();
  for (const finding of findings) {
    if (free.length === 0) break;
    const bearing = TILE_BEARING[finding.author] ?? 0;
    let best = 0;
    let bestCost = Number.POSITIVE_INFINITY;
    free.forEach((slot, index) => {
      const cost = slot.ring + (turn(slot.bearing, bearing) / 180) * WEDGE;
      if (cost < bestCost) {
        best = index;
        bestCost = cost;
      }
    });
    const [slot] = free.splice(best, 1);
    if (slot) placed.set(finding.id, { x: slot.x, y: slot.y });
  }
  return placed;
}

/** The middle of a curve between two points. Reversing the points bends it the other way. */
function control(from: Point, to: Point, bend: number): Point {
  return {
    x: (from.x + to.x) / 2 - (to.y - from.y) * bend,
    y: (from.y + to.y) / 2 + (to.x - from.x) * bend,
  };
}

export function arcPath(from: Point, to: Point, bend = 0.12): string {
  const middle = control(from, to, bend);
  return `M ${from.x} ${from.y} Q ${middle.x} ${middle.y} ${to.x} ${to.y}`;
}

export function arcPoints(from: Point, to: Point, samples = 16, bend = 0.12): Point[] {
  const middle = control(from, to, bend);
  return Array.from({ length: samples + 1 }, (_, index) => {
    const t = index / samples;
    const u = 1 - t;
    return {
      x: u * u * from.x + 2 * u * t * middle.x + t * t * to.x,
      y: u * u * from.y + 2 * u * t * middle.y + t * t * to.y,
    };
  });
}

export const distance = (a: Point, b: Point): number => Math.hypot(a.x - b.x, a.y - b.y);

/** Where a message to this recipient lands. The Orchestrator's board sits under the mosaic. */
export function anchorOf(actor: string): Point {
  return NODE[actor as AgentKey] ?? CENTRE;
}

/** The view that frames an agent, for presenter mode. */
export function cameraOn(point: Point): string {
  const width = 620;
  const height = width * (STAGE.height / STAGE.width);
  const x = Math.min(Math.max(point.x - width / 2, 0), STAGE.width - width);
  const y = Math.min(Math.max(point.y - height / 2, 0), STAGE.height - height);
  return `${x} ${y} ${width} ${height}`;
}
