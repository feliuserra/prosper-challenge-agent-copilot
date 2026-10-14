import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import { parseEdgeId, type AgentFlowEdge } from "./derive";
import { backEdgeGeometry, edgeGeometry, selfLoopGeometry } from "./edgePath";

/** An arrow turning right, for the edge label. */
function BranchIcon() {
  return (
    <svg className="edge-label-icon" viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
      <path
        d="M5 4v7a4 4 0 0 0 4 4h11M15 10l5 5-5 5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * A transition, labelled with its description (the function name when it has
 * none) and problem badges; the function name is in the tooltip. Clicking the
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
  const label = data?.label ?? fn;
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
          title={label === fn ? fn : `${fn}: ${label}`}
          // By the edge's id: `source` is a collapsed stage's card when the edge leaves one.
          onClick={() => useAgentStore.getState().select({ kind: "edge", ...parseEdgeId(id) })}
        >
          <BranchIcon />
          <span className="edge-label-text">{label}</span>
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
