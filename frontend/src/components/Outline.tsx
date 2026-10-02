import { useAgentStore } from "../store/agentStore";

// Read-only view of the open agent until the canvas lands (#4). Clicking selects.
export function Outline() {
  const agent = useAgentStore((s) => s.agent);
  const selection = useAgentStore((s) => s.selection);
  const select = useAgentStore((s) => s.select);
  if (!agent) return <p className="muted">No agent open.</p>;

  return (
    <ul className="outline">
      {agent.nodes.map((node) => (
        <li key={node.name}>
          <button
            className={selection?.kind === "node" && selection.name === node.name ? "selected" : ""}
            onClick={() => select({ kind: "node", name: node.name })}
          >
            {node.name}
          </button>
          {agent.initial_node === node.name && <span className="badge">Start</span>}
          {node.end && <span className="badge">End</span>}
          <ul>
            {(node.edges ?? []).map((edge) => (
              <li key={edge.function}>
                <button
                  className={
                    selection?.kind === "edge" &&
                    selection.source === node.name &&
                    selection.function === edge.function
                      ? "selected"
                      : ""
                  }
                  onClick={() => select({ kind: "edge", source: node.name, function: edge.function })}
                >
                  {edge.function}
                </button>{" "}
                → {edge.target}
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
