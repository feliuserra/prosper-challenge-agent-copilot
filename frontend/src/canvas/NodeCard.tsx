import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

import { NODE_WIDTH } from "../agent/layout";
import type { AgentFlowNode } from "./derive";

/** First non-empty line of the node's first task message. */
function taskSummary(content: string | undefined): string {
  return (content ?? "").split("\n").find((line) => line.trim())?.trim() ?? "";
}

export const NodeCard = memo(function NodeCard({ data, selected }: NodeProps<AgentFlowNode>) {
  const { node, isStart, status = [] } = data;
  const task = taskSummary(node.task_messages?.[0]?.content);
  return (
    <div className={selected ? "node-card selected" : "node-card"} style={{ width: NODE_WIDTH }}>
      <Handle type="target" position={Position.Top} />
      <div className="node-card-header">
        <span className="node-card-name" title={node.name}>
          {node.name}
        </span>
        {isStart && <span className="badge start">Start</span>}
        {node.end && <span className="badge end">End</span>}
        <span className="node-card-status">
          {status.map((s, i) => (
            <span key={i} className={`badge ${s.tone}`} title={s.title}>
              {s.label}
            </span>
          ))}
        </span>
      </div>
      <div className={task ? "node-card-task" : "node-card-task muted"} title={task}>
        {task || "No task yet"}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
});
