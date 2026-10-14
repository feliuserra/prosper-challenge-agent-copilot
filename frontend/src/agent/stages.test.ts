import { describe, expect, it } from "vitest";

import type { Agent } from "./schema";
import { callOrder, STAGE_TONES, stageOf, stagesOf } from "./stages";

const edge = (target: string) => ({ function: `to_${target}`, description: "", target });

// start -> a -> b, start -> c; d is not reachable. Listed out of call order on purpose.
const agent = (stages: Record<string, string>): Agent => ({
  name: "s",
  initial_node: "start",
  nodes: [
    { name: "d" },
    { name: "b" },
    { name: "a", edges: [edge("b")] },
    { name: "start", edges: [edge("a"), edge("c")] },
    { name: "c", edges: [edge("start")] },
  ].map((n) => (stages[n.name] !== undefined ? { ...n, stage: stages[n.name] } : n)),
});

describe("stageOf", () => {
  it("is the trimmed stage, or null when it is missing or blank", () => {
    expect(stageOf({ name: "n", stage: "  Book " })).toBe("Book");
    expect(stageOf({ name: "n", stage: "  " })).toBeNull();
    expect(stageOf({ name: "n" })).toBeNull();
  });
});

describe("callOrder", () => {
  it("is breadth first from the start node, then unreachable nodes in file order", () => {
    expect(callOrder(agent({})).map((n) => n.name)).toEqual(["start", "a", "c", "b", "d"]);
  });

  it("is file order when the start node is missing", () => {
    expect(callOrder({ ...agent({}), initial_node: "gone" }).map((n) => n.name)).toEqual(["d", "b", "a", "start", "c"]);
  });
});

describe("stagesOf", () => {
  it("orders stages and their nodes in call order and gives each a tone", () => {
    const stages = stagesOf(agent({ d: "Later", b: "Book", start: "Identify", a: "Identify ", c: "Book" }));
    expect(stages).toEqual([
      { name: "Identify", nodes: ["start", "a"], tone: 0 },
      { name: "Book", nodes: ["c", "b"], tone: 1 },
      { name: "Later", nodes: ["d"], tone: 2 },
    ]);
  });

  it("has no stages when no node has one, and reuses tones past the last", () => {
    expect(stagesOf(agent({}))).toEqual([]);
    const many: Agent = {
      name: "m",
      initial_node: "n0",
      nodes: Array.from({ length: STAGE_TONES + 1 }, (_, i) => ({ name: `n${i}`, stage: `S${i}` })),
    };
    expect(stagesOf(many).map((s) => s.tone)).toEqual([0, 1, 2, 3, 4, 5, 0]);
  });
});
