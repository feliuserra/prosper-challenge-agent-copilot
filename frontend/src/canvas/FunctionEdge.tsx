import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import type { AgentFlowEdge } from "./derive";

/** A transition, labelled with its function name. Clicking the label selects it. */
export function FunctionEdge(props: EdgeProps<AgentFlowEdge>) {
  const { id, source, data, selected, markerEnd, sourcePosition, targetPosition } = props;
  const offset = data?.offset ?? 0;
  const [path, labelX, labelY] = getBezierPath({
    sourceX: props.sourceX + offset,
    sourceY: props.sourceY,
    targetX: props.targetX + offset,
    targetY: props.targetY,
    sourcePosition,
    targetPosition,
  });
  const fn = data?.function ?? "";

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        <button
          className={selected ? "edge-label nodrag nopan selected" : "edge-label nodrag nopan"}
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          onClick={() => useAgentStore.getState().select({ kind: "edge", source, function: fn })}
        >
          {fn}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}
