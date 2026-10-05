import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import type { AgentFlowEdge } from "./derive";
import { backEdgeGeometry, edgeGeometry, selfLoopGeometry } from "./edgePath";

/**
 * A transition, labelled with its function name and problem badges. Clicking the
 * label selects it. The edge a test call took last is animated and marked.
 */
export function FunctionEdge(props: EdgeProps<AgentFlowEdge>) {
  const { id, source, target, data, selected, markerEnd } = props;
  const ends = {
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    lane: data?.lane ?? 0,
  };
  const route = data?.route;
  const { path, labelX, labelY, labelAlign } =
    source === target ? selfLoopGeometry(ends) : route ? backEdgeGeometry(ends, route) : edgeGeometry(ends);
  const fn = data?.function ?? "";
  const status = data?.status ?? [];
  const className = [
    "edge-label",
    "nodrag",
    "nopan",
    selected && "selected",
    data?.active && "active",
    status.length > 0 && status[0].tone,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        <button
          className={className}
          style={{
            transform: `translate(${labelAlign === "start" ? "0" : "-50%"}, -50%) translate(${labelX}px, ${labelY}px)`,
          }}
          onClick={() => useAgentStore.getState().select({ kind: "edge", source, function: fn })}
        >
          {fn}
          {status.map((s) => (
            <span key={s.tone} className={`badge ${s.tone}`} title={s.title}>
              {s.label}
            </span>
          ))}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}
