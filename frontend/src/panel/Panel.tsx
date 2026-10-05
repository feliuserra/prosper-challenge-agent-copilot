import { useMemo, useState } from "react";

import { agentFileText } from "../agent/file";
import type { Agent } from "../agent/schema";
import { useAgentStore } from "../store/agentStore";
import { AgentPanel } from "./AgentPanel";
import { EdgePanel } from "./EdgePanel";
import { NodePanel } from "./NodePanel";

/**
 * Editor for the selection: a node, an edge, or (nothing selected) the agent.
 * The JSON tab shows the whole agent instead, read-only.
 */
export function Panel() {
  const agent = useAgentStore((s) => s.agent);
  const selection = useAgentStore((s) => s.selection);
  const [tab, setTab] = useState<"edit" | "json">("edit");
  if (!agent) return null;

  let content = <AgentPanel agent={agent} />;
  if (tab === "json") {
    content = <JsonView agent={agent} />;
  } else if (selection?.kind === "node") {
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
  return (
    <aside className="panel nokey">
      <div className="panel-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "edit"} onClick={() => setTab("edit")}>
          Edit
        </button>
        <button role="tab" aria-selected={tab === "json"} onClick={() => setTab("json")}>
          JSON
        </button>
      </div>
      {content}
    </aside>
  );
}

/** The agent as it would be saved or exported, updated as it is edited. */
function JsonView({ agent }: { agent: Agent }) {
  const text = useMemo(() => agentFileText(agent), [agent]);
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <>
      <div className="row json-view-header">
        <span className="muted">Read-only, unsaved changes included. <code>ui</code> is the canvas position.</span>
        <button className="small" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="json-view mono">{text}</pre>
    </>
  );
}
