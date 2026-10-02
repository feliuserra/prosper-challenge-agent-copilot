import { getBezierPath, Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { NODE_WIDTH } from "../agent/layout";
import { edgeGeometry, LABEL_STACK, selfLoopGeometry } from "./edgePath";

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
