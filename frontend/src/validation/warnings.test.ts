import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { Agent, Edge, Node } from "../agent/schema";
import { agentWarnings } from "./warnings";

// A small agent with no warnings; each fixture below breaks one thing.
const edge = (fn: string, target: string, extra: Partial<Edge> = {}): Edge => ({
  function: fn,
  description: "When it is time.",
  target,
  ...extra,
});
const node = (name: string, extra: Partial<Node> = {}): Node => ({
  name,
  task_messages: [{ role: "developer", content: "Do the step." }],
  ...extra,
});
const clean = (): Agent => ({
  name: "a",
  initial_node: "start",
  nodes: [node("start", { edges: [edge("next", "done")] }), node("done", { end: true })],
});

/** `clean()` with node `name` changed. */
function withNode(name: string, extra: Partial<Node>): Agent {
  const agent = clean();
  agent.nodes = agent.nodes.map((n) => (n.name === name ? { ...n, ...extra } : n));
  return agent;
}

const where = (agent: Agent) => agentWarnings(agent).map(({ node, edge, message }) => ({ node, edge, message }));

describe("agentWarnings", () => {
  it("finds nothing in a clean agent or in the example agent", () => {
    expect(agentWarnings(clean())).toEqual([]);
    const example = JSON.parse(readFileSync(new URL("../../../backend/agents/prosper-scheduler.json", import.meta.url), "utf8")) as Agent;
    expect(agentWarnings(example)).toEqual([]);
  });

  it("marks every problem as a warning", () => {
    const agent = withNode("start", { task_messages: [] });
    expect(agentWarnings(agent).map((w) => w.severity)).toEqual(["warning"]);
  });

  it("flags nodes the start node cannot reach, even through other unreachable nodes", () => {
    const agent = clean();
    agent.nodes.push(node("orphan", { edges: [edge("go", "island")] }), node("island", { end: true }));
    expect(where(agent)).toEqual([
      { node: "orphan", edge: null, message: "Not reachable from the start node 'start'." },
      { node: "island", edge: null, message: "Not reachable from the start node 'start'." },
    ]);
  });

  it("follows self-loops and cycles without flagging reachable nodes", () => {
    const agent = withNode("start", { edges: [edge("again", "start"), edge("next", "done")] });
    agent.nodes.push(node("back", { edges: [edge("loop", "start")] }));
    agent.nodes[0].edges!.push(edge("detour", "back"));
    expect(agentWarnings(agent)).toEqual([]);
  });

  it("does not flag every node as unreachable when the start node is missing", () => {
    const agent = { ...clean(), initial_node: "gone" };
    expect(agentWarnings(agent)).toEqual([]);
  });

  it("flags a dead end: a node with no transitions that is not an end node", () => {
    expect(where(withNode("done", { end: undefined }))).toEqual([
      { node: "done", edge: null, message: expect.stringMatching(/^Dead end/) },
    ]);
    expect(where(withNode("done", { end: false, edges: [] }))).toHaveLength(1);
  });

  it("flags an end node with transitions", () => {
    expect(where(withNode("done", { edges: [edge("more", "start")] }))).toEqual([
      { node: "done", edge: null, message: expect.stringMatching(/^End node has transitions/) },
    ]);
  });

  it("flags a node with no task messages, and each empty one", () => {
    expect(where(withNode("start", { task_messages: undefined }))).toEqual([
      { node: "start", edge: null, message: expect.stringMatching(/^No task message/) },
    ]);
    const messages = [
      { role: "developer", content: "Do it." },
      { role: "developer", content: "  " },
      { role: "developer", content: "" },
    ];
    expect(where(withNode("start", { task_messages: messages }))).toEqual([
      { node: "start", edge: null, message: "Task message #2 is empty." },
      { node: "start", edge: null, message: "Task message #3 is empty." },
    ]);
  });

  it("flags a transition with an empty description, on the edge", () => {
    expect(where(withNode("start", { edges: [edge("next", "done", { description: " " })] }))).toEqual([
      { node: "start", edge: "next", message: expect.stringMatching(/^No description/) },
    ]);
  });

  it("flags required names that are not collected fields", () => {
    const fields = { properties: { name: { type: "string" } }, required: ["name", "dob"] };
    expect(where(withNode("start", { edges: [edge("next", "done", fields)] }))).toEqual([
      { node: "start", edge: "next", message: "'dob' is required but is not a collected field." },
    ]);
    const noFields = { required: ["dob"] };
    expect(where(withNode("start", { edges: [edge("next", "done", noFields)] }))).toHaveLength(1);
  });

  it("does not throw on shapes the backend reports as errors", () => {
    const agent = clean() as unknown as { nodes: Record<string, unknown>[] };
    agent.nodes[0].edges = [{ function: "next", description: "d", target: "nowhere", required: "dob" }];
    agent.nodes[1].task_messages = "hello";
    expect(() => agentWarnings(agent as unknown as Agent)).not.toThrow();
  });
});
