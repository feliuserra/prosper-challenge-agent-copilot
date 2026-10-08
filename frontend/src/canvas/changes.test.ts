import { readFileSync } from "node:fs";
import type { NodeChange } from "@xyflow/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "../agent/schema";
import { useAgentStore } from "../store/agentStore";
import { handleEdgeChanges, handleNodeChanges } from "./changes";
import type { AgentFlowNode } from "./derive";

const exampleText = readFileSync(new URL("../../../backend/tests/fixtures/linear-agent.json", import.meta.url), "utf8");

const store = () => useAgentStore.getState();
const history = () => useAgentStore.temporal.getState();
const ui = (name: string) => store().agent!.nodes.find((n) => n.name === name)!.ui;
const noop = () => {};

const move = (id: string, x: number, y: number, dragging: boolean): NodeChange<AgentFlowNode> => ({
  type: "position",
  id,
  position: { x, y },
  dragging,
});

/** What React Flow sends for a drag: frames with dragging: true, then a final dragging: false. */
function drag(ids: string[], frames: number) {
  for (let i = 1; i <= frames; i++) handleNodeChanges(ids.map((id) => move(id, i * 10.4, i * 5.6, true)), noop);
  handleNodeChanges(ids.map((id) => move(id, frames * 10.4, frames * 5.6, false)), noop);
}

beforeEach(() => {
  store().open("prosper-scheduler", JSON.parse(exampleText) as Agent);
});

describe("dragging", () => {
  it("writes positions to the store on every frame, rounded", () => {
    handleNodeChanges([move("greeting", 10.4, 20.6, true)], noop);
    expect(ui("greeting")).toEqual({ x: 10, y: 21 });
    handleNodeChanges([move("greeting", 30, 40, true)], noop);
    expect(ui("greeting")).toEqual({ x: 30, y: 40 });
    handleNodeChanges([move("greeting", 30, 40, false)], noop);
  });

  it("one drag is exactly one history entry, and undo restores the position before it", () => {
    const before = ui("greeting");
    drag(["greeting"], 12);
    expect(history().pastStates).toHaveLength(1);
    expect(ui("greeting")).toEqual({ x: 125, y: 67 });
    history().undo();
    expect(ui("greeting")).toEqual(before);
  });

  it("a multi-node drag is one entry, and history resumes afterwards", () => {
    drag(["greeting", "confirm"], 5);
    expect(history().pastStates).toHaveLength(1);
    expect(history().isTracking).toBe(true);
    store().updateAgent({ name: "Renamed" });
    expect(history().pastStates).toHaveLength(2);
  });

  it("two drags are two entries", () => {
    drag(["greeting"], 3);
    drag(["offer_times"], 3);
    expect(history().pastStates).toHaveLength(2);
  });

  it("keyboard moves (dragging: false) are one entry each", () => {
    handleNodeChanges([move("greeting", 5, 0, false)], noop);
    handleNodeChanges([move("greeting", 10, 0, false)], noop);
    expect(history().pastStates).toHaveLength(2);
  });
});

describe("selection and measurements", () => {
  it("selects nodes and edges, and clears only the element being deselected", () => {
    handleNodeChanges([{ type: "select", id: "greeting", selected: true }], noop);
    expect(store().selection).toEqual({ kind: "node", name: "greeting" });
    handleEdgeChanges([{ type: "select", id: "offer_times::select_time", selected: true }]);
    expect(store().selection).toEqual({ kind: "edge", source: "offer_times", function: "select_time" });
    // Deselecting the previously selected node does not clear the edge.
    handleNodeChanges([{ type: "select", id: "greeting", selected: false }], noop);
    expect(store().selection).toEqual({ kind: "edge", source: "offer_times", function: "select_time" });
    handleEdgeChanges([{ type: "select", id: "offer_times::select_time", selected: false }]);
    expect(store().selection).toBeNull();
  });

  it("reports measured sizes without touching the agent", () => {
    const agent = store().agent;
    const onMeasured = vi.fn();
    handleNodeChanges([{ type: "dimensions", id: "greeting", dimensions: { width: 240, height: 61 } }], onMeasured);
    expect(onMeasured).toHaveBeenCalledWith("greeting", { width: 240, height: 61 });
    expect(store().agent).toBe(agent);
  });
});
