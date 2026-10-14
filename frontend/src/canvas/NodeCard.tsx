import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

import { NODE_WIDTH } from "../agent/layout";
import { displayName } from "../agent/names";
import type { AgentFlowNode } from "./derive";

/** The node's first task message on one paragraph; the card shows its first two lines. */
function taskSummary(content: string | undefined): string {
  return (content ?? "").replace(/\s+/g, " ").trim();
}

/** A person in a circle: a step of the conversation. */
function NodeIcon() {
  return (
    <svg className="node-card-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9.5" />
        <circle cx="12" cy="10" r="3" />
        <path d="M6.2 18.6a6.5 6.5 0 0 1 11.6 0" />
      </g>
    </svg>
  );
}

/** A wrench: a round head with a slot, on a handle. */
function WrenchIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
      <path d="M20.43 5.69A5 5 0 1 1 18.31 3.57L16 5.88 18.12 8Z" fill="currentColor" />
      <path d="M13 11 5 19" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
    </svg>
  );
}

export const NodeCard = memo(function NodeCard({ data, selected }: NodeProps<AgentFlowNode>) {
  const { node, isStart, status = [], active } = data;
  const task = taskSummary(node.task_messages?.[0]?.content);
  const tools = node.tools ?? [];
  const className = ["node-card", selected && "selected", active && "active"].filter(Boolean).join(" ");
  return (
    <div className={className} style={{ width: NODE_WIDTH }} title={active ? "The test call is here" : undefined}>
      <Handle type="target" position={Position.Top} />
      <div className="node-card-main">
        <div className="node-card-header">
          <NodeIcon />
          <span className="node-card-name" title={node.name}>
            {displayName(node.name)}
          </span>
          {isStart && <span className="badge start">Start</span>}
          {node.end && <span className="badge end">End</span>}
          <span className="node-card-status">
            {status.map((s) => (
              <span key={s.tone} className={`badge ${s.tone}`} title={s.title}>
                {s.label}
              </span>
            ))}
          </span>
        </div>
        <div className={task ? "node-card-task" : "node-card-task muted"} title={task}>
          {task || "No task yet"}
        </div>
      </div>
      {tools.length > 0 && (
        <div className="node-card-footer">
          <span className="node-card-tools" title={`Tools: ${tools.join(", ")}`}>
            <WrenchIcon />
            {tools.length} {tools.length === 1 ? "tool" : "tools"}
          </span>
        </div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
});
