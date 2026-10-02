import { describe, expect, it } from "vitest";

import type { Agent } from "../agent/schema";
import { edgeId, parseEdgeId, toFlowEdges, toFlowNodes } from "./derive";

const agent: Agent = {
  name: "a",
  initial_node: "start",
  nodes: [
    {
      name: "start",
      ui: { x: 10, y: 20 },
      edges: [
        { function: "book", description: "", target: "next" },
        { function: "cancel", description: "", target: "next" },
        { function: "lost", description: "", target: "nowhere" },
      ],
    },
    { name: "next", ui: { x: 0, y: 200 }, end: true },
  ],
};

describe("toFlowNodes", () => {
  it("uses the name as id and the stored position, and marks start and selection", () => {
    const nodes = toFlowNodes(agent, { kind: "node", name: "next" }, { next: { width: 240, height: 60 } });
    expect(nodes.map((n) => [n.id, n.position, n.data.isStart, n.selected])).toEqual([
      ["start", { x: 10, y: 20 }, true, false],
      ["next", { x: 0, y: 200 }, false, true],
    ]);
    expect(nodes[1].measured).toEqual({ width: 240, height: 60 });
    expect(nodes[1].data.node).toBe(agent.nodes[1]);
  });
});

describe("toFlowEdges", () => {
  const edges = toFlowEdges(agent, { kind: "edge", source: "start", function: "cancel" });

  it("uses `${source}::${function}` ids and skips edges to missing nodes", () => {
    expect(edges.map((e) => e.id)).toEqual(["start::book", "start::cancel"]);
    expect(edges.map((e) => e.selected)).toEqual([false, true]);
    expect(edges.every((e) => e.reconnectable === "target")).toBe(true);
  });

  it("spreads edges between the same two nodes so both labels show", () => {
    const [a, b] = edges.map((e) => e.data!.offset);
    expect(a).toBe(-b);
    expect(a).not.toBe(0);
  });
});

describe("edge ids", () => {
  it("round-trip, even when the node name contains '::'", () => {
    expect(parseEdgeId(edgeId("a::b", "go_to_c"))).toEqual({ source: "a::b", function: "go_to_c" });
  });
});
