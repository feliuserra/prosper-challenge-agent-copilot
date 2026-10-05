import { readFileSync } from "node:fs";
import { getBezierPath, Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { NODE_HEIGHT, NODE_WIDTH, withPositions } from "../agent/layout";
import type { Agent } from "../agent/schema";
import { toFlowEdges } from "./derive";
import {
  backEdgeGeometry,
  edgeGeometry,
  LABEL_STACK,
  routeBackEdges,
  selfLoopGeometry,
  type Box,
  type RoutedEdge,
} from "./edgePath";

// A rendered label is about 20px tall (12px text, padding and border).
const LABEL_HEIGHT = 20;

const bezier = (sourceX: number, sourceY: number, targetX: number, targetY: number) =>
  getBezierPath({ sourceX, sourceY, sourcePosition: Position.Bottom, targetX, targetY, targetPosition: Position.Top });

describe("edgeGeometry", () => {
  it("is React Flow's default bezier for a lone edge, forwards and backwards", () => {
    for (const [sx, sy, tx, ty] of [
      [0, 64, 0, 154],
      [10, 64, 400, 300],
      [0, 400, 300, 0],
    ]) {
      const [path, labelX, labelY] = bezier(sx, sy, tx, ty);
      expect(edgeGeometry({ sourceX: sx, sourceY: sy, targetX: tx, targetY: ty, lane: 0 })).toEqual({
        path,
        labelX,
        labelY,
        labelAlign: "center",
      });
    }
  });

  it("keeps both ends on the handles and stacks labels of parallel edges apart", () => {
    const ends = { sourceX: 0, sourceY: 64, targetX: 0, targetY: 154 };
    const [a, b] = [-0.5, 0.5].map((lane) => edgeGeometry({ ...ends, lane }));
    for (const g of [a, b]) {
      expect(g.path.startsWith("M0,64 ")).toBe(true);
      expect(g.path.endsWith(" 0,154")).toBe(true);
    }
    expect(a.path).not.toBe(b.path);
    expect(b.labelY - a.labelY).toBe(LABEL_STACK);
    expect(LABEL_STACK).toBeGreaterThan(LABEL_HEIGHT);
  });
});

describe("selfLoopGeometry", () => {
  it("goes round the right side of the node, with the label beside it", () => {
    // Bottom handle at y=64, top handle at y=0 of a card centred on x=120.
    const g = selfLoopGeometry({ sourceX: 120, sourceY: 64, targetX: 120, targetY: 0, lane: 0 });
    expect(g.path.startsWith("M120,64 ")).toBe(true);
    expect(g.path.endsWith(" 120,0")).toBe(true);
    expect(g.labelX).toBeGreaterThan(120 + NODE_WIDTH / 2);
    expect(g.labelAlign).toBe("start");
  });
});

/** Points along an SVG path made of M, L and C segments, as edgeGeometry and friends write them. */
function samplePath(path: string): [number, number][] {
  const tokens = path.match(/[MLC]|-?[\d.]+/g)!;
  const points: [number, number][] = [];
  let at: [number, number] = [0, 0];
  const num = () => Number(tokens.shift());
  while (tokens.length) {
    const command = tokens.shift();
    if (command === "M") at = [num(), num()];
    else if (command === "L") {
      const to: [number, number] = [num(), num()];
      for (let t = 0; t <= 1; t += 0.02) points.push([at[0] + (to[0] - at[0]) * t, at[1] + (to[1] - at[1]) * t]);
      at = to;
    } else if (command === "C") {
      const [c1, c2, to]: [number, number][] = [
        [num(), num()],
        [num(), num()],
        [num(), num()],
      ];
      for (let t = 0; t <= 1; t += 0.02) {
        const u = 1 - t;
        points.push([
          u ** 3 * at[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * to[0],
          u ** 3 * at[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * to[1],
        ]);
      }
      at = to;
    }
  }
  return points;
}

const inside = ([x, y]: [number, number], b: Box) => x > b.x && x < b.x + b.width && y > b.y && y < b.y + b.height;
const box = (x: number, y: number): Box => ({ x, y, width: NODE_WIDTH, height: NODE_HEIGHT });
const edge = (source: string, target: string, label = `${source}_to_${target}`): RoutedEdge => ({
  id: `${source}::${label}`,
  source,
  target,
  label,
});

describe("back edges", () => {
  // The fixture agent (the original example) as the editor lays it out, plus a "start over" edge from
  // the last node back to the first.
  const example = JSON.parse(
    readFileSync(new URL("../../../backend/tests/fixtures/linear-agent.json", import.meta.url), "utf8"),
  ) as Agent;
  const laidOut = withPositions(example);
  const withBackEdge: Agent = {
    ...laidOut,
    nodes: laidOut.nodes.map((n) =>
      n.name === "confirm"
        ? { ...n, edges: [{ function: "start_over", description: "", target: "greeting" }] }
        : n,
    ),
  };

  it("in the fixture agent, confirm -> greeting does not cross collect_details or offer_times", () => {
    const flow = toFlowEdges(withBackEdge, null);
    const back = flow.find((e) => e.id === "confirm::start_over")!;
    // Forward edges keep the plain curve.
    expect(flow.filter((e) => e.data!.route).map((e) => e.id)).toEqual(["confirm::start_over"]);

    const boxes = Object.fromEntries(withBackEdge.nodes.map((n) => [n.name, box(n.ui!.x, n.ui!.y)]));
    // Handle positions as React Flow passes them: bottom centre of the source, top centre of the target.
    const { path } = backEdgeGeometry(
      {
        sourceX: boxes.confirm.x + NODE_WIDTH / 2,
        sourceY: boxes.confirm.y + NODE_HEIGHT,
        targetX: boxes.greeting.x + NODE_WIDTH / 2,
        targetY: boxes.greeting.y,
      },
      back.data!.route!,
    );
    const points = samplePath(path);
    expect(points.length).toBeGreaterThan(100);
    for (const name of ["greeting", "collect_details", "offer_times", "confirm"]) {
      expect(points.filter((p) => inside(p, boxes[name]))).toEqual([]);
    }
  });

  it("are only edges into a node above the source; self-loops and forward edges are not routed", () => {
    const boxes = new Map([
      ["a", box(0, 0)],
      ["b", box(0, 200)],
    ]);
    const routes = routeBackEdges(boxes, [edge("a", "b"), edge("a", "a"), edge("b", "a")]);
    expect([...routes.keys()]).toEqual(["b::b_to_a"]);
    expect(routes.get("b::b_to_a")!.x).toBeGreaterThan(NODE_WIDTH);
  });

  it("clear a node in between that sticks out further right", () => {
    const boxes = new Map([
      ["a", box(0, 0)],
      ["wide", box(150, 150)],
      ["b", box(0, 300)],
    ]);
    const route = routeBackEdges(boxes, [edge("b", "a")]).get("b::b_to_a")!;
    expect(route.x).toBeGreaterThan(150 + NODE_WIDTH);
  });

  it("ignore nodes outside their vertical span", () => {
    const boxes = new Map([
      ["a", box(0, 0)],
      ["b", box(0, 200)],
      ["below", box(500, 600)],
    ]);
    expect(routeBackEdges(boxes, [edge("b", "a")]).get("b::b_to_a")!.x).toBeLessThan(500);
  });

  it("clear a self-loop and its label on a node in between", () => {
    const boxes = new Map([
      ["a", box(0, 0)],
      ["mid", box(0, 150)],
      ["b", box(0, 300)],
    ]);
    const plain = routeBackEdges(boxes, [edge("b", "a")]).get("b::b_to_a")!;
    const looped = routeBackEdges(boxes, [edge("b", "a"), edge("mid", "mid", "clarify_the_request")]).get("b::b_to_a")!;
    const loop = selfLoopGeometry({ sourceX: NODE_WIDTH / 2, sourceY: 214, targetX: NODE_WIDTH / 2, targetY: 150, lane: 0 });
    expect(looped.x).toBeGreaterThan(plain.x);
    expect(looped.x).toBeGreaterThan(loop.labelX + "clarify_the_request".length * 7);
  });

  it("get lanes when they share a column, shorter spans inside, and stack their labels", () => {
    const boxes = new Map([
      ["a", box(0, 0)],
      ["b", box(0, 150)],
      ["c", box(0, 300)],
    ]);
    const routes = routeBackEdges(boxes, [edge("c", "a"), edge("c", "b"), edge("c", "a", "again")]);
    const long = routes.get("c::c_to_a")!;
    const short = routes.get("c::c_to_b")!;
    const parallel = routes.get("c::again")!;
    expect(short.lane).toBe(0);
    expect(new Set([long.lane, parallel.lane])).toEqual(new Set([1, 2]));
    expect(long.x).toBeGreaterThan(short.x);

    // Two back edges between the same nodes: labels at the same height without lanes.
    const ends = { sourceX: 120, sourceY: 364, targetX: 120, targetY: 0 };
    const [g1, g2] = [long, parallel].map((r) => backEdgeGeometry(ends, r));
    expect(Math.abs(g1.labelY - g2.labelY)).toBe(LABEL_STACK);
  });

  it("that do not overlap vertically share lane 0", () => {
    const boxes = new Map([
      ["a", box(0, 0)],
      ["b", box(0, 150)],
      ["c", box(0, 300)],
      ["d", box(0, 450)],
    ]);
    const routes = routeBackEdges(boxes, [edge("b", "a"), edge("d", "c")]);
    expect([...routes.values()].map((r) => r.lane)).toEqual([0, 0]);
  });
});
