import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";

import type { Agent } from "../agent/schema";
import { selectIsDirty, useAgentStore } from "./agentStore";
import { redo, undo } from "./history";

const exampleText = readFileSync(new URL("../../../backend/tests/fixtures/linear-agent.json", import.meta.url), "utf8");

const store = () => useAgentStore.getState();
const temporal = () => useAgentStore.temporal.getState();

// Fixture (the original example agent): greeting -choose_intent-> collect_details -record_details-> offer_times -select_time-> confirm (end)
beforeEach(() => {
  store().open("prosper-scheduler", JSON.parse(exampleText) as Agent);
});

/** Runs `edit` (one history step), then checks that undo restores the agent exactly and redo reapplies it. */
function expectUndoable(edit: () => void) {
  const before = store().agent;
  const beforeJson = JSON.stringify(before);
  const dirtyBefore = selectIsDirty(store());
  edit();
  const after = store().agent;
  expect(JSON.stringify(after)).not.toBe(beforeJson);

  undo();
  // The same object, so nothing (key order, untouched nodes) can differ.
  expect(store().agent).toBe(before);
  expect(JSON.stringify(store().agent)).toBe(beforeJson);
  expect(selectIsDirty(store())).toBe(dirtyBefore);

  redo();
  expect(store().agent).toBe(after);
}

describe("undo and redo", () => {
  it("restore the agent exactly after a rename (with its cascade to targets and the start node)", () => {
    expectUndoable(() => expect(store().renameNode("greeting", "hello").ok).toBe(true));
    expectUndoable(() => expect(store().renameNode("offer_times", "slots").ok).toBe(true));
  });

  it("restore the agent exactly after a delete (with the incoming edges it removed)", () => {
    expectUndoable(() => expect(store().deleteNode("offer_times").ok).toBe(true));
  });

  it("restore the agent exactly after a connect", () => {
    expectUndoable(() => store().connect("confirm", "greeting"));
  });

  it("go back one step at a time", () => {
    const start = store().agent;
    store().renameNode("greeting", "hello");
    const renamed = store().agent;
    store().connect("confirm", "hello");
    undo();
    expect(store().agent).toBe(renamed);
    undo();
    expect(store().agent).toBe(start);
  });

  it("drop a selection the step removed, and keep one that still exists", () => {
    const fn = store().connect("confirm", "greeting");
    expect(store().selection).toEqual({ kind: "edge", source: "confirm", function: fn });
    undo();
    expect(store().selection).toBeNull();

    store().select({ kind: "node", name: "greeting" });
    redo();
    expect(store().selection).toEqual({ kind: "node", name: "greeting" });

    store().select({ kind: "node", name: "offer_times" });
    store().deleteNode("collect_details");
    undo();
    redo();
    expect(store().selection).toEqual({ kind: "node", name: "offer_times" });

    store().deleteNode("offer_times");
    expect(store().selection).toBeNull();
    store().select({ kind: "node", name: "confirm" });
    undo();
    expect(store().selection).toEqual({ kind: "node", name: "confirm" });
  });

  it("do nothing at either end of history", () => {
    const before = store().agent;
    undo();
    redo();
    expect(store().agent).toBe(before);
    expect(temporal().pastStates).toHaveLength(0);
  });
});
