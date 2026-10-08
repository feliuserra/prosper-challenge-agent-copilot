import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";

import type { Agent } from "../agent/schema";
import { selectIsDirty, useAgentStore } from "./agentStore";

const exampleText = readFileSync(new URL("../../../backend/tests/fixtures/linear-agent.json", import.meta.url), "utf8");

const store = () => useAgentStore.getState();
const agent = () => store().agent!;
const node = (name: string) => agent().nodes.find((n) => n.name === name);
const edgeFns = (name: string) => (node(name)?.edges ?? []).map((e) => e.function);

// Fixture (the original example agent): greeting -choose_intent-> collect_details -record_details-> offer_times -select_time-> confirm (end)
beforeEach(() => {
  store().open("prosper-scheduler", JSON.parse(exampleText) as Agent);
});

describe("open, save state and history", () => {
  it("starts clean and becomes dirty on change", () => {
    expect(selectIsDirty(store())).toBe(false);
    store().updateAgent({ name: "Renamed" });
    expect(selectIsDirty(store())).toBe(true);
    store().markSaved();
    expect(selectIsDirty(store())).toBe(false);
  });

  it("an unchanged agent serialises to the same JSON apart from added positions", () => {
    // Compact form: the file's own whitespace is not preserved (the backend
    // writes indent=2), only its values and key order. `open` adds `ui` to
    // every node because the example has no positions.
    const withoutUi = { ...agent(), nodes: agent().nodes.map(({ ui, ...rest }) => rest) };
    expect(JSON.stringify(withoutUi)).toBe(JSON.stringify(JSON.parse(exampleText)));
  });

  it("lays out an agent without positions on open, without marking it unsaved", () => {
    expect(agent().nodes.every((n) => n.ui)).toBe(true);
    expect(selectIsDirty(store())).toBe(false);
  });

  it("keeps saved positions on open and places only the missing ones", () => {
    const example = JSON.parse(exampleText) as Agent;
    example.nodes[0].ui = { x: 500, y: -40 };
    example.nodes[1].ui = { x: 500, y: 200 };
    store().open("prosper-scheduler", example);
    expect(node("greeting")?.ui).toEqual({ x: 500, y: -40 });
    expect(node("collect_details")?.ui).toEqual({ x: 500, y: 200 });
    // collect_details -> offer_times: placed below its source.
    expect(node("offer_times")?.ui?.x).toBe(500);
    expect(node("offer_times")?.ui?.y).toBeGreaterThan(200);
    expect(selectIsDirty(store())).toBe(false);
  });

  it("tidyLayout is one history step", () => {
    store().moveNode("greeting", { x: 999, y: 999 });
    const before = useAgentStore.temporal.getState().pastStates.length;
    store().tidyLayout();
    expect(useAgentStore.temporal.getState().pastStates).toHaveLength(before + 1);
    expect(node("greeting")?.ui).not.toEqual({ x: 999, y: 999 });
  });

  it("a new unsaved agent is dirty", () => {
    store().open("new-one", { name: "n", initial_node: "s", nodes: [{ name: "s" }] }, false);
    expect(selectIsDirty(store())).toBe(true);
  });

  it("records agent changes in history, not selection changes", () => {
    const { temporal } = useAgentStore;
    expect(temporal.getState().pastStates).toHaveLength(0);
    store().select({ kind: "node", name: "greeting" });
    expect(temporal.getState().pastStates).toHaveLength(0);
    store().updateAgent({ name: "Renamed" });
    expect(temporal.getState().pastStates).toHaveLength(1);
    temporal.getState().undo();
    expect(agent().name).toBe("Prosper Scheduler");
  });

  it("opening another agent clears history", () => {
    store().updateAgent({ name: "Renamed" });
    store().open("other", JSON.parse(exampleText) as Agent);
    expect(useAgentStore.temporal.getState().pastStates).toHaveLength(0);
  });
});

describe("addNode", () => {
  it("adds a uniquely named node and selects it", () => {
    const first = store().addNode({ x: 5, y: 6 });
    const second = store().addNode();
    expect(first).toBe("new_node");
    expect(second).toBe("new_node_2");
    expect(node(first)?.ui).toEqual({ x: 5, y: 6 });
    expect(store().selection).toEqual({ kind: "node", name: second });
  });

  it("places a node added without a position below the others, moving none", () => {
    const before = agent().nodes.map((n) => n.ui);
    const name = store().addNode();
    const lowest = Math.max(...before.map((p) => p!.y));
    expect(node(name)?.ui?.y).toBeGreaterThan(lowest);
    expect(agent().nodes.slice(0, -1).map((n) => n.ui)).toEqual(before);
  });
});

describe("renameNode", () => {
  it("cascades to edge targets, initial_node and the selection", () => {
    store().select({ kind: "node", name: "greeting" });
    expect(store().renameNode("greeting", "hello")).toEqual({ ok: true });
    expect(node("hello")).toBeDefined();
    expect(agent().initial_node).toBe("hello");
    expect(store().selection).toEqual({ kind: "node", name: "hello" });

    store().select({ kind: "edge", source: "offer_times", function: "select_time" });
    store().renameNode("confirm", "wrap_up");
    expect(node("offer_times")?.edges?.[0].target).toBe("wrap_up");
    store().renameNode("offer_times", "slots");
    expect(store().selection).toEqual({ kind: "edge", source: "slots", function: "select_time" });
  });

  it("rejects duplicates and empty names, leaving the store unchanged", () => {
    const before = agent();
    expect(store().renameNode("greeting", "confirm")).toMatchObject({ ok: false });
    expect(store().renameNode("greeting", "   ")).toMatchObject({ ok: false });
    expect(agent()).toBe(before);
  });

  it("trims whitespace", () => {
    store().renameNode("greeting", "  hello ");
    expect(node("hello")).toBeDefined();
  });
});

describe("deleteNode", () => {
  it("removes the node with its outgoing and incoming edges", () => {
    store().connect("greeting", "offer_times");
    expect(store().deleteNode("offer_times")).toEqual({ ok: true });
    expect(node("offer_times")).toBeUndefined();
    expect(edgeFns("collect_details")).toEqual([]); // record_details targeted offer_times
    expect(edgeFns("greeting")).toEqual(["choose_intent"]); // the new edge is gone too
  });

  it("clears a selection that pointed at the node or its edges", () => {
    store().select({ kind: "edge", source: "collect_details", function: "record_details" });
    store().deleteNode("offer_times");
    expect(store().selection).toBeNull();

    store().select({ kind: "node", name: "collect_details" });
    store().deleteNode("confirm");
    expect(store().selection).toEqual({ kind: "node", name: "collect_details" });
  });

  it("refuses to delete the start node", () => {
    const before = agent();
    expect(store().deleteNode("greeting")).toMatchObject({ ok: false });
    expect(agent()).toBe(before);
  });
});

describe("connect", () => {
  it("adds an edge with a placeholder name and empty description, and selects it", () => {
    const fn = store().connect("greeting", "confirm");
    expect(fn).toBe("go_to_confirm");
    expect(node("greeting")?.edges?.at(-1)).toEqual({ function: "go_to_confirm", description: "", target: "confirm" });
    expect(store().selection).toEqual({ kind: "edge", source: "greeting", function: "go_to_confirm" });
  });

  it("suffixes the placeholder when the name exists in that node", () => {
    expect(store().connect("greeting", "confirm")).toBe("go_to_confirm");
    expect(store().connect("greeting", "confirm")).toBe("go_to_confirm_2");
    // Another node can reuse the name.
    expect(store().connect("offer_times", "confirm")).toBe("go_to_confirm");
  });

  it("works on a node without an edges key", () => {
    store().open("x", { name: "x", initial_node: "a", nodes: [{ name: "a" }, { name: "b" }] });
    store().connect("a", "b");
    expect(edgeFns("a")).toEqual(["go_to_b"]);
  });
});

describe("updateEdge", () => {
  it("updates fields and follows a rename with the selection", () => {
    store().select({ kind: "edge", source: "greeting", function: "choose_intent" });
    expect(store().updateEdge("greeting", "choose_intent", { function: "pick", description: "d" })).toEqual({
      ok: true,
    });
    expect(node("greeting")?.edges?.[0]).toMatchObject({ function: "pick", description: "d" });
    expect(store().selection).toEqual({ kind: "edge", source: "greeting", function: "pick" });
  });

  it("rejects a function name already used in the node, leaving the store unchanged", () => {
    store().connect("greeting", "confirm");
    const before = agent();
    const result = store().updateEdge("greeting", "go_to_confirm", { function: "choose_intent" });
    expect(result).toMatchObject({ ok: false });
    expect(agent()).toBe(before);
  });

  it("keeps unknown edge keys", () => {
    store().open("x", {
      name: "x",
      initial_node: "a",
      nodes: [{ name: "a", edges: [{ function: "f", description: "", target: "a", priority: 1 }] }],
    });
    store().updateEdge("a", "f", { description: "now" });
    expect(node("a")?.edges?.[0]).toEqual({ function: "f", description: "now", target: "a", priority: 1 });
  });
});

describe("deleteEdge, setInitialNode, moveNode, updateNode", () => {
  it("deleteEdge removes the edge and clears its selection", () => {
    store().select({ kind: "edge", source: "greeting", function: "choose_intent" });
    store().deleteEdge("greeting", "choose_intent");
    expect(edgeFns("greeting")).toEqual([]);
    expect(store().selection).toBeNull();
  });

  it("setInitialNode accepts existing nodes only", () => {
    expect(store().setInitialNode("confirm")).toEqual({ ok: true });
    expect(agent().initial_node).toBe("confirm");
    expect(store().setInitialNode("nowhere")).toMatchObject({ ok: false });
  });

  it("moveNode writes ui and keeps other ui keys", () => {
    store().updateNode("greeting", { ui: { x: 0, y: 0, collapsed: true } });
    store().moveNode("greeting", { x: 10, y: 20 });
    expect(node("greeting")?.ui).toEqual({ x: 10, y: 20, collapsed: true });
  });

  it("updateNode leaves other nodes untouched (same objects)", () => {
    const other = node("confirm");
    store().updateNode("greeting", { end: true });
    expect(node("greeting")?.end).toBe(true);
    expect(node("confirm")).toBe(other);
  });
});

describe("patches", () => {
  it("undefined removes a key from a node, an edge or the agent, keeping key order", () => {
    store().updateNode("greeting", { role_message: "Be brief." });
    expect(node("greeting")?.role_message).toBe("Be brief.");
    store().updateNode("greeting", { role_message: undefined });
    expect("role_message" in node("greeting")!).toBe(false);

    store().updateEdge("collect_details", "record_details", { required: undefined });
    expect("required" in node("collect_details")!.edges![0]).toBe(false);

    const keys = Object.keys(agent());
    store().updateAgent({ persona: undefined });
    expect(Object.keys(agent())).toEqual(keys.filter((k) => k !== "persona"));
  });
});
