import type { Agent } from "../agent/schema";
import type { Problem } from "./problems";

// Authoring warnings (#9): things that are allowed but probably not what the
// author meant. Computed on the client from the draft, on every change. They
// never block a test call; only backend errors do (validationStore).
//
// Each check reads the draft defensively: it may be mid-edit or have errors the
// backend reports, and a warning must never throw because of them.

const warning = (message: string, node: string | null = null, edge: string | null = null): Problem => ({
  severity: "warning",
  message,
  node,
  edge,
});

const isBlank = (value: unknown) => typeof value !== "string" || value.trim() === "";
const list = <T>(value: T[] | undefined): T[] => (Array.isArray(value) ? value : []);

/** Every warning for the agent, by node in file order. */
export function agentWarnings(agent: Agent): Problem[] {
  const reachable = reachableNodes(agent);
  const warnings: Problem[] = [];

  for (const node of agent.nodes) {
    const edges = list(node.edges);
    const messages = list(node.task_messages);

    if (reachable && !reachable.has(node.name)) {
      warnings.push(warning(`Not reachable from the start node '${agent.initial_node}'.`, node.name));
    }
    if (!node.end && edges.length === 0) {
      warnings.push(warning("Dead end: no transitions and not an end node, so the call gets stuck here.", node.name));
    }
    if (node.end && edges.length > 0) {
      warnings.push(warning("End node has transitions. The call hangs up after its reply, so they are never taken.", node.name));
    }
    if (messages.length === 0) {
      warnings.push(warning("No task message: the LLM gets no instructions for this step.", node.name));
    }
    messages.forEach((message, i) => {
      if (isBlank(message?.content)) warnings.push(warning(`Task message #${i + 1} is empty.`, node.name));
    });

    for (const edge of edges) {
      if (isBlank(edge.description)) {
        warnings.push(
          warning("No description: the LLM reads it to decide when to take this transition.", node.name, edge.function),
        );
      }
      const defined = new Set(Object.keys(edge.properties ?? {}));
      for (const name of list(edge.required)) {
        if (!defined.has(name)) {
          warnings.push(warning(`'${name}' is required but is not a collected field.`, node.name, edge.function));
        }
      }
    }
  }
  return warnings;
}

/**
 * Names of the nodes a call can reach from the start node. `null` when the
 * start node does not exist: that is a backend error, and flagging every node
 * as unreachable on top of it would only add noise.
 */
function reachableNodes(agent: Agent): Set<string> | null {
  const byName = new Map(agent.nodes.map((n) => [n.name, n]));
  if (!byName.has(agent.initial_node)) return null;
  const seen = new Set([agent.initial_node]);
  const queue = [agent.initial_node];
  while (queue.length) {
    for (const edge of list(byName.get(queue.shift()!)?.edges)) {
      if (byName.has(edge.target) && !seen.has(edge.target)) {
        seen.add(edge.target);
        queue.push(edge.target);
      }
    }
  }
  return seen;
}
