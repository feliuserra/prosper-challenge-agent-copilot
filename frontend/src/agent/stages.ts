import type { Agent, Node } from "./schema";

// Stages group nodes on the canvas (#50). A node's stage is its `stage` field;
// the list of stages, their order and their colours are derived from the nodes,
// so nothing can get out of step with them.

/** How many stage colours there are (`.tone-0` to `.tone-5` in index.css). */
export const STAGE_TONES = 6;

export type Stage = { name: string; nodes: string[]; tone: number };

/** A node's stage, or null when it has none. */
export function stageOf(node: Node): string | null {
  return node.stage?.trim() || null;
}

/** The nodes in the order a call can reach them: breadth first from the start node, then the rest in file order. */
export function callOrder(agent: Agent): Node[] {
  const byName = new Map(agent.nodes.map((n) => [n.name, n]));
  const seen = new Set<string>();
  const order: Node[] = [];
  const queue = byName.has(agent.initial_node) ? [agent.initial_node] : [];
  for (const name of queue) {
    if (seen.has(name)) continue;
    seen.add(name);
    order.push(byName.get(name)!);
    for (const edge of order.at(-1)!.edges ?? []) if (byName.has(edge.target)) queue.push(edge.target);
  }
  return [...order, ...agent.nodes.filter((n) => !seen.has(n.name))];
}

/** The agent's stages, ordered by their first node in call order, each with its nodes in that order. */
export function stagesOf(agent: Agent): Stage[] {
  const stages = new Map<string, string[]>();
  for (const node of callOrder(agent)) {
    const stage = stageOf(node);
    if (stage) stages.set(stage, [...(stages.get(stage) ?? []), node.name]);
  }
  return [...stages].map(([name, nodes], i) => ({ name, nodes, tone: i % STAGE_TONES }));
}
