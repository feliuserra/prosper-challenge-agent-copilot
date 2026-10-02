import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import type { AgentFlowEdge } from "./derive";
import { edgeGeometry, selfLoopGeometry } from "./edgePath";

/** A transition, labelled with its function name. Clicking the label selects it. */
export function FunctionEdge(props: EdgeProps<AgentFlowEdge>) {
  const { id, source, target, data, selected, markerEnd } = props;
  const ends = {
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    lane: data?.lane ?? 0,
  };
  const { path, labelX, labelY, labelAlign } = source === target ? selfLoopGeometry(ends) : edgeGeometry(ends);
  const fn = data?.function ?? "";

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        <button
          className={selected ? "edge-label nodrag nopan selected" : "edge-label nodrag nopan"}
          style={{
            transform: `translate(${labelAlign === "start" ? "0" : "-50%"}, -50%) translate(${labelX}px, ${labelY}px)`,
          }}
          onClick={() => useAgentStore.getState().select({ kind: "edge", source, function: fn })}
        >
          {fn}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}
