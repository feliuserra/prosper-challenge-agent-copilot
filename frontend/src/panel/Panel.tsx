import { useAgentStore } from "../store/agentStore";
import { AgentPanel } from "./AgentPanel";
import { EdgePanel } from "./EdgePanel";
import { NodePanel } from "./NodePanel";

/** Editor for the selection: a node, an edge, or (nothing selected) the agent. */
export function Panel() {
  const agent = useAgentStore((s) => s.agent);
  const selection = useAgentStore((s) => s.selection);
  if (!agent) return null;

  let content = <AgentPanel agent={agent} />;
  if (selection?.kind === "node") {
    const node = agent.nodes.find((n) => n.name === selection.name);
    if (node) content = <NodePanel key={node.name} node={node} agent={agent} />;
  } else if (selection?.kind === "edge") {
    const edge = agent.nodes.find((n) => n.name === selection.source)?.edges?.find((e) => e.function === selection.function);
    if (edge) {
      content = <EdgePanel key={`${selection.source}::${edge.function}`} source={selection.source} edge={edge} agent={agent} />;
    }
  }
  // `nokey`: React Flow ignores key presses from here, so Backspace on a focused
  // panel button never deletes the selected node.
  return <aside className="panel nokey">{content}</aside>;
}
