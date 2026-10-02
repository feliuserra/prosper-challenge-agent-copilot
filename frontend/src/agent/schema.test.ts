import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { Agent } from "./schema";
import { blankAgent } from "./templates";

const examplePath = new URL("../../../backend/agents/prosper-scheduler.json", import.meta.url);
const exampleText = readFileSync(examplePath, "utf8");

describe("Agent schema", () => {
  it("accepts the example agent", () => {
    expect(Agent.safeParse(JSON.parse(exampleText)).success).toBe(true);
  });

  it("keeps keys it does not model, at every level", () => {
    const agent = JSON.parse(exampleText);
    agent.notes = "agent-level";
    agent.nodes[0].color = "blue";
    agent.nodes[0].edges[0].priority = 1;
    agent.nodes[0].task_messages[0].cache = true;
    agent.nodes[0].pre_actions = [{ type: "tts_say", text: "Hi", extra: { nested: [1, 2] } }];
    agent.nodes[0].ui = { x: 1, y: 2, zoom: 3 };
    const parsed = Agent.parse(agent);
    expect(parsed).toEqual(agent);
  });

  it("adds no defaults, so a missing field stays missing", () => {
    const minimal = { name: "a", initial_node: "s", nodes: [{ name: "s" }] };
    expect(Agent.parse(minimal)).toEqual(minimal);
  });

  it("rejects a shape the editor cannot work with", () => {
    expect(Agent.safeParse({ name: "a", nodes: [] }).success).toBe(false);
    expect(Agent.safeParse({ name: "a", initial_node: "s", nodes: [{ name: 1 }] }).success).toBe(false);
  });

  it("accepts a blank agent", () => {
    expect(Agent.safeParse(blankAgent("New")).success).toBe(true);
  });
});
