import { describe, expect, it } from "vitest";

import type { Agent } from "../agent/schema";
import type { Problem } from "../validation/problems";
import { edgeId, parseEdgeId, statusBadges, toFlowEdges, toFlowNodes } from "./derive";

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
    // Only the selected edge can be reconnected.
    expect(edges.map((e) => e.reconnectable)).toEqual([false, "target"]);
  });

  it("gives edges between the same two nodes their own lanes, a lone edge lane 0", () => {
    expect(edges.map((e) => e.data!.lane)).toEqual([-0.5, 0.5]);
    const loop: Agent = {
      name: "l",
      initial_node: "a",
      nodes: [{ name: "a", edges: [{ function: "again", description: "", target: "a" }] }],
    };
    expect(toFlowEdges(loop, null)[0].data!.lane).toBe(0);
  });
});

describe("statusBadges", () => {
  const problem = (node: string | null, edge: string | null, message: string, severity: Problem["severity"] = "error") => ({
    severity,
    message,
    node,
    edge,
  });

  it("puts node problems on the node and edge problems on the edge, matched by name", () => {
    const { nodes, edges } = statusBadges(agent, [
      problem("next", null, "Each task message needs a role."),
      problem("start", "book", "Property 'date' needs a type."),
    ]);
    expect([...nodes.keys()]).toEqual(["next"]);
    expect([...edges.keys()]).toEqual(["start::book"]);
    expect(edges.get("start::book")).toEqual([
      { tone: "error", label: "1 error", title: "Property 'date' needs a type." },
    ]);
  });

  it("shows several problems as one badge per severity, errors first", () => {
    const { nodes } = statusBadges(agent, [
      problem("start", null, "w", "warning"),
      problem("start", null, "a"),
      problem("start", null, "b"),
    ]);
    expect(nodes.get("start")).toEqual([
      { tone: "error", label: "2 errors", title: "a\nb" },
      { tone: "warning", label: "1 warning", title: "w" },
    ]);
  });

  it("puts a problem of an edge that is not drawn on its node, naming the edge", () => {
    const { nodes, edges } = statusBadges(agent, [problem("start", "lost", "Edge targets unknown node 'nowhere'.")]);
    expect(edges.size).toBe(0);
    expect(nodes.get("start")![0].title).toBe("lost: Edge targets unknown node 'nowhere'.");
  });

  it("gives agent-level problems and unknown nodes no badge", () => {
    const { nodes, edges } = statusBadges(agent, [problem(null, null, "Agent needs a name."), problem("gone", null, "x")]);
    expect(nodes.size + edges.size).toBe(0);
  });

  it("hands the badges to the flow nodes and edges", () => {
    const badges = statusBadges(agent, [problem("next", null, "n"), problem("start", "cancel", "e")]);
    const flowNodes = toFlowNodes(agent, null, {}, badges.nodes);
    const flowEdges = toFlowEdges(agent, null, badges.edges);
    expect(flowNodes.map((n) => n.data.status?.[0].title)).toEqual([undefined, "n"]);
    expect(flowEdges.map((e) => e.data!.status?.[0].title)).toEqual([undefined, "e"]);
  });
});

describe("a test call's position", () => {
  it("marks the active node and animates the edge taken", () => {
    const nodes = toFlowNodes(agent, null, {}, new Map(), "next");
    expect(nodes.map((n) => n.data.active)).toEqual([false, true]);
    const edges = toFlowEdges(agent, null, new Map(), edgeId("start", "cancel"));
    expect(edges.map((e) => [e.animated, e.data!.active])).toEqual([
      [false, false],
      [true, true],
    ]);
  });

  it("marks nothing outside a call or for a node that is gone", () => {
    expect(toFlowNodes(agent, null).some((n) => n.data.active)).toBe(false);
    expect(toFlowNodes(agent, null, {}, new Map(), "renamed").some((n) => n.data.active)).toBe(false);
    expect(toFlowEdges(agent, null).some((e) => e.animated)).toBe(false);
  });
});

describe("edge ids", () => {
  it("round-trip, even when the node name contains '::'", () => {
    expect(parseEdgeId(edgeId("a::b", "go_to_c"))).toEqual({ source: "a::b", function: "go_to_c" });
  });
});
