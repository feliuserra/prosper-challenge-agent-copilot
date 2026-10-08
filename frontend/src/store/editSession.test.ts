import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";

import type { Agent } from "../agent/schema";
import { useAgentStore } from "./agentStore";
import { beginEdit, edited, endEdit } from "./editSession";

const exampleText = readFileSync(new URL("../../../backend/tests/fixtures/linear-agent.json", import.meta.url), "utf8");
const store = () => useAgentStore.getState();
const history = () => useAgentStore.temporal.getState();

/** Type `text` one character at a time into the agent's persona, as a field would. */
function type(owner: object, text: string) {
  for (let i = 1; i <= text.length; i++) {
    store().updateAgent({ persona: text.slice(0, i) });
    edited(owner);
  }
}

beforeEach(() => {
  history().resume();
  store().open("prosper-scheduler", JSON.parse(exampleText) as Agent);
});

describe("edit sessions", () => {
  it("make one history entry per focused field, and undo restores the text before it", () => {
    const before = store().agent!.persona;
    const field = {};
    beginEdit(field);
    type(field, "Be brief.");
    endEdit(field);
    expect(history().pastStates).toHaveLength(1);
    expect(history().isTracking).toBe(true);
    history().undo();
    expect(store().agent!.persona).toBe(before);
  });

  it("two sessions are two entries", () => {
    const a = {};
    const b = {};
    beginEdit(a);
    type(a, "one");
    beginEdit(b); // focusing another field ends the first session
    type(b, "two");
    endEdit(b);
    expect(history().pastStates).toHaveLength(2);
  });

  it("ending a session that is not the current one changes nothing", () => {
    const field = {};
    beginEdit(field);
    type(field, "abc");
    endEdit({}); // e.g. another field unmounting
    expect(history().isTracking).toBe(false);
    endEdit(field);
    expect(history().isTracking).toBe(true);
  });

  it("never resumes history that something else paused (e.g. a drag)", () => {
    const field = {};
    beginEdit(field);
    history().pause(); // a drag started without this session writing anything
    endEdit(field);
    expect(history().isTracking).toBe(false);
    history().resume();
  });
});
