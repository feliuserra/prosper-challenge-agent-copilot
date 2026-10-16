import { withPositions } from "../agent/layout";
import type { Agent, Node } from "../agent/schema";

// What a proposal changes in the draft, node by node, for the canvas (#31): added and
// changed nodes are marked, removed ones are listed in the proposal card. A node's
// position and stage are left out, as in the backend's agent hash.

export type Mark = "added" | "changed";

export interface NodeDiff {
  marks: Map<string, Mark>;
  removed: string[];
}

/** A node without what the canvas alone uses. */
function behaviour(node: Node): string {
  const { ui: _ui, stage: _stage, ...rest } = node;
  return JSON.stringify(rest);
}

export function nodeDiff(proposal: Agent, draft: Agent | null): NodeDiff {
  const before = new Map((draft?.nodes ?? []).map((n) => [n.name, n]));
  const marks = new Map<string, Mark>();
  for (const node of proposal.nodes) {
    const old = before.get(node.name);
    if (!old) marks.set(node.name, "added");
    else if (behaviour(old) !== behaviour(node)) marks.set(node.name, "changed");
  }
  const names = new Set(proposal.nodes.map((n) => n.name));
  return { marks, removed: [...before.keys()].filter((name) => !names.has(name)) };
}

/**
 * `agent` with canvas positions: a node keeps its own, else takes the position of the
 * node of the same name in `like` (the draft, or the previous step of a build), so the
 * graph does not jump while it is built; nodes new to both are placed near their sources.
 */
export function positioned(agent: Agent, like: Agent | null): Agent {
  const at = new Map((like?.nodes ?? []).filter((n) => n.ui).map((n) => [n.name, n.ui!]));
  const nodes = agent.nodes.map((n) => (n.ui || !at.has(n.name) ? n : { ...n, ui: at.get(n.name)! }));
  return withPositions({ ...agent, nodes });
}
