import type { Agent } from "./schema";

/** A new blank agent: one start node, ready to edit. Passes backend validation. */
export function blankAgent(name: string): Agent {
  return {
    name,
    initial_node: "start",
    nodes: [
      {
        name: "start",
        task_messages: [{ role: "developer", content: "" }],
        edges: [],
        ui: { x: 0, y: 0 },
      },
    ],
  };
}

export const EXAMPLE_AGENT_ID = "prosper-scheduler";
