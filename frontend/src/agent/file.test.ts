import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { agentFileText, parseAgentFile } from "./file";

const exampleText = readFileSync(new URL("../../../backend/agents/prosper-scheduler.json", import.meta.url), "utf8");

describe("agent files", () => {
  it("round-trip an agent: values, key order and unknown keys", () => {
    const parsed = parseAgentFile(exampleText);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    const withExtras = { ...parsed.agent, extra: { kept: true }, nodes: [{ ...parsed.agent.nodes[0], ui: { x: 1, y: 2 } }] };
    const again = parseAgentFile(agentFileText(withExtras));
    expect(again.ok && JSON.stringify(again.agent)).toBe(JSON.stringify(withExtras));
  });

  it("explain why a file is not an agent", () => {
    expect(parseAgentFile("{nope")).toMatchObject({ ok: false, error: expect.stringMatching(/^not valid JSON/) });
    expect(parseAgentFile("[]")).toMatchObject({ ok: false, error: expect.stringMatching(/^not an agent/) });
    const noTarget = { name: "a", initial_node: "s", nodes: [{ name: "s", edges: [{ function: "f", description: "" }] }] };
    expect(parseAgentFile(JSON.stringify(noTarget))).toMatchObject({
      ok: false,
      error: expect.stringContaining("nodes.0.edges.0.target"),
    });
  });

  it("accept an agent with errors the backend reports, such as a missing start node", () => {
    expect(parseAgentFile(JSON.stringify({ name: "a", initial_node: "gone", nodes: [] })).ok).toBe(true);
  });
});
