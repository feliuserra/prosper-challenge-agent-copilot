import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { autoLayout, freeSpot, nearestFreeSpot, NODE_HEIGHT, NODE_WIDTH, placeMissing, withPositions } from "./layout";
import type { Agent, Position } from "./schema";

const example = () =>
  JSON.parse(
    readFileSync(new URL("../../../backend/tests/fixtures/linear-agent.json", import.meta.url), "utf8"),
  ) as Agent;

const pos = (agent: Agent, name: string) => agent.nodes.find((n) => n.name === name)!.ui!;
const overlap = (a: Position, b: Position) =>
  Math.abs(a.x - b.x) < NODE_WIDTH && Math.abs(a.y - b.y) < NODE_HEIGHT;

// A small graph: a -> b, a -> c, b -> d.
const graph = (ui: Record<string, Position> = {}): Agent => ({
  name: "g",
  initial_node: "a",
  nodes: [
    { name: "a", edges: [{ function: "to_b", description: "", target: "b" }, { function: "to_c", description: "", target: "c" }] },
    { name: "b", edges: [{ function: "to_d", description: "", target: "d" }] },
    { name: "c" },
    { name: "d" },
  ].map((n) => (ui[n.name] ? { ...n, ui: ui[n.name] } : n)),
});

describe("autoLayout", () => {
  it("positions every node top to bottom along the edges, on integer coordinates", () => {
    const agent = autoLayout(example());
    const ys = ["greeting", "collect_details", "offer_times", "confirm"].map((n) => pos(agent, n).y);
    expect(ys).toEqual([...ys].sort((a, b) => a - b));
    expect(new Set(ys).size).toBe(4);
    for (const node of agent.nodes) {
      expect(Number.isInteger(node.ui!.x) && Number.isInteger(node.ui!.y)).toBe(true);
    }
  });

  it("does not overlap nodes and keeps other ui keys", () => {
    const input = graph();
    input.nodes[0].ui = { x: 1, y: 1, collapsed: true };
    const agent = autoLayout(input);
    const all = agent.nodes.map((n) => n.ui!);
    for (const [i, a] of all.entries()) for (const b of all.slice(i + 1)) expect(overlap(a, b)).toBe(false);
    expect(pos(agent, "a").collapsed).toBe(true);
  });
});

describe("freeSpot", () => {
  it("keeps a free spot and moves right past occupied ones", () => {
    expect(freeSpot({ x: 0.4, y: 0.6 }, [{ x: 1000, y: 0 }])).toEqual({ x: 0, y: 1 });
    const spot = freeSpot({ x: 0, y: 0 }, [{ x: 10, y: 10 }]);
    expect(spot.y).toBe(0);
    expect(spot.x).toBeGreaterThanOrEqual(NODE_WIDTH);
  });
});

describe("nearestFreeSpot", () => {
  const area = { x: -400, y: -300, width: 800, height: 600 };

  it("keeps the start when it is free", () => {
    expect(nearestFreeSpot({ x: 3.4, y: 7 }, [{ x: 0, y: 300 }], area)).toEqual({ x: 3, y: 7 });
  });

  it("picks the closest free spot inside the area", () => {
    const taken = [{ x: 0, y: 0 }];
    const spot = nearestFreeSpot({ x: 0, y: 0 }, taken, area);
    expect(overlap(spot, taken[0])).toBe(false);
    expect(spot.x).toBeGreaterThanOrEqual(area.x);
    expect(spot.x + NODE_WIDTH).toBeLessThanOrEqual(area.x + area.width);
    expect(Math.hypot(spot.x, spot.y)).toBeLessThan(NODE_WIDTH + NODE_HEIGHT);
  });

  it("falls back to the start when nothing in the area is free", () => {
    const small = { x: 0, y: 0, width: NODE_WIDTH, height: NODE_HEIGHT };
    expect(nearestFreeSpot({ x: 0, y: 0 }, [{ x: 0, y: 0 }], small)).toEqual({ x: 0, y: 0 });
  });
});

describe("placeMissing", () => {
  it("returns the same agent when every node has a position", () => {
    const agent = autoLayout(graph());
    expect(placeMissing(agent)).toBe(agent);
  });

  it("places nodes below their source without moving positioned nodes", () => {
    const agent = placeMissing(graph({ a: { x: 100, y: 0 } }));
    expect(pos(agent, "a")).toEqual({ x: 100, y: 0 });
    // b and c both hang off a: side by side, below it. d follows b.
    expect(pos(agent, "b").y).toBeGreaterThan(0);
    expect(pos(agent, "c").y).toBe(pos(agent, "b").y);
    expect(overlap(pos(agent, "b"), pos(agent, "c"))).toBe(false);
    expect(pos(agent, "d").y).toBeGreaterThan(pos(agent, "b").y);
  });

  it("puts nodes with no positioned source at the fallback", () => {
    const agent = placeMissing(graph({ b: { x: 0, y: 0 }, c: { x: 400, y: 0 }, d: { x: 0, y: 200 } }), {
      x: 900,
      y: 900,
    });
    expect(pos(agent, "a")).toEqual({ x: 900, y: 900 });
  });
});

describe("withPositions", () => {
  it("runs a full layout only when no node has a position", () => {
    expect(withPositions(graph())).toEqual(autoLayout(graph()));
    const partial = graph({ a: { x: 7, y: 7 } });
    expect(pos(withPositions(partial), "a")).toEqual({ x: 7, y: 7 });
  });
});
