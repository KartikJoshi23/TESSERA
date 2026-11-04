import { describe, expect, it } from "vitest";
import {
  arcPoints,
  cameraOn,
  CENTRE,
  distance,
  layoutTiles,
  NODE,
  STAGE,
  TILE_CAPACITY,
  TILE_RADIUS,
} from "./geometry";

const findings = (count: number, author = "CMA") =>
  Array.from({ length: count }, (_, index) => ({ id: `F-${index}`, author }));

describe("the mosaic", () => {
  it("gives every finding its own place", () => {
    const slots = layoutTiles(findings(40));
    const places = new Set([...slots.values()].map((slot) => `${slot.x},${slot.y}`));
    expect(places.size).toBe(40);
  });

  it("keeps a tile where it landed as more arrive", () => {
    const early = layoutTiles(findings(10));
    const later = layoutTiles(findings(30));
    for (const [id, slot] of early) expect(later.get(id)).toEqual(slot);
  });

  it("never lets two tiles overlap", () => {
    const places = [...layoutTiles(findings(TILE_CAPACITY)).values()];
    for (const [index, a] of places.entries()) {
      for (const b of places.slice(index + 1)) {
        expect(distance(a, b)).toBeGreaterThan(TILE_RADIUS * 1.7);
      }
    }
  });

  it("grows each agent's tiles toward that agent", () => {
    const slots = layoutTiles([
      { id: "left", author: "CMA" },
      { id: "right", author: "VARA" },
      { id: "below", author: "CLN" },
    ]);
    expect(slots.get("left")?.x ?? 0).toBeLessThan(CENTRE.x);
    expect(slots.get("right")?.x ?? 0).toBeGreaterThan(CENTRE.x);
    expect(slots.get("below")?.y ?? 0).toBeGreaterThan(CENTRE.y);
  });

  it("stays clear of every agent's tile", () => {
    const places = [...layoutTiles(findings(TILE_CAPACITY)).values()];
    for (const key of ["JUR", "CMA", "DFSA", "VARA", "CLN"] as const) {
      const closest = Math.min(...places.map((place) => distance(place, NODE[key])));
      expect(closest).toBeGreaterThan(36 + TILE_RADIUS);
    }
  });

  it("copes with more findings than it can hold", () => {
    expect(layoutTiles(findings(TILE_CAPACITY + 5)).size).toBe(TILE_CAPACITY);
  });
});

describe("the paths", () => {
  it("run from one point to the other", () => {
    const points = arcPoints(NODE.CMA, NODE.REC);
    expect(points[0]).toEqual(NODE.CMA);
    expect(points.at(-1)).toEqual(NODE.REC);
  });

  it("take a different lane in each direction", () => {
    const out = arcPoints(NODE.CMA, NODE.REC, 2)[1];
    const back = arcPoints(NODE.REC, NODE.CMA, 2)[1];
    expect(out).not.toEqual(back);
  });
});

describe("the presenter camera", () => {
  it("stays inside the stage", () => {
    for (const point of Object.values(NODE)) {
      const [x = 0, y = 0, width = 0, height = 0] = cameraOn(point).split(" ").map(Number);
      expect(x).toBeGreaterThanOrEqual(0);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(x + width).toBeLessThanOrEqual(STAGE.width);
      expect(y + height).toBeLessThanOrEqual(STAGE.height);
    }
  });
});
