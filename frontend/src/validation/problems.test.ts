import { describe, expect, it } from "vitest";

import type { Agent } from "../agent/schema";
import { problemLocation, problemNodes, problemSelection, type Problem } from "./problems";

const agent: Agent = {
  name: "a",
  initial_node: "start",
  nodes: [
    {
      name: "start",
      edges: [
        { function: "book", description: "", target: "next" },
        { function: "again", description: "", target: "start" },
        { function: "lost", description: "", target: "nowhere" },
      ],
    },
    { name: "next" },
  ],
};

const error = (node: string | null, edge: string | null = null): Problem => ({
  severity: "error",
  message: "m",
  node,
  edge,
});

describe("problemSelection", () => {
  it("points at the edge, the node or (null) the agent", () => {
    expect(problemSelection(error("start", "book"))).toEqual({ kind: "edge", source: "start", function: "book" });
    expect(problemSelection(error("start"))).toEqual({ kind: "node", name: "start" });
    expect(problemSelection(error(null))).toBeNull();
  });
});

describe("problemLocation", () => {
  it("names the node and function, or the agent", () => {
    expect(problemLocation(error("start", "book"))).toBe("start › book");
    expect(problemLocation(error("start"))).toBe("start");
    expect(problemLocation(error(null))).toBe("Agent");
  });
});

describe("problemNodes", () => {
  it("brings a node, or an edge's source and target, into view", () => {
    expect(problemNodes(agent, error("next"))).toEqual(["next"]);
    expect(problemNodes(agent, error("start", "book"))).toEqual(["start", "next"]);
  });

  it("leaves out a self-loop's repeat, a missing target and missing nodes", () => {
    expect(problemNodes(agent, error("start", "again"))).toEqual(["start"]);
    expect(problemNodes(agent, error("start", "lost"))).toEqual(["start"]);
    expect(problemNodes(agent, error("gone"))).toEqual([]);
    expect(problemNodes(agent, error(null))).toEqual([]);
  });
});
