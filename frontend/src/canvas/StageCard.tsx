import { Fragment, memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

import { NODE_WIDTH } from "../agent/layout";
import { displayName } from "../agent/names";
import { useAgentStore } from "../store/agentStore";
import type { StageFlowNode } from "./derive";
import { HeatLines, heatStyle } from "./NodeCard";

/** A chevron pointing right (collapsed) or down (expanded). */
export function Chevron({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path
        d={open ? "M6 9l6 6 6-6" : "M9 6l6 6-6 6"}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * A collapsed stage (#51): its name, its steps in order and its nodes' badges,
 * the size of a node card. Edges into and out of the stage end here. The chevron
 * expands it; dragging it moves all its nodes.
 */
export const StageCard = memo(function StageCard({ data, selected }: NodeProps<StageFlowNode>) {
  const { stage, status = [], activeStep, heat } = data;
  const look = heatStyle(heat);
  const className = [
    "node-card",
    "stage-card",
    `tone-${stage.tone}`,
    selected && "selected",
    activeStep && "active",
    look.className,
  ]
    .filter(Boolean)
    .join(" ");
  const steps = stage.nodes.length;
  return (
    <div
      className={className}
      style={{ width: NODE_WIDTH, ...look.style }}
      title={activeStep ? `The test call is in ${displayName(activeStep)}` : undefined}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="node-card-main">
        <div className="node-card-header">
          <button
            className="stage-card-toggle nodrag"
            title="Expand the stage"
            aria-label={`Expand ${stage.name}`}
            onClick={() => useAgentStore.getState().setCollapsed(stage.name, false)}
          >
            <Chevron open={false} />
          </button>
          <span className="node-card-name" title={stage.name}>
            {stage.name}
          </span>
          <span className="stage-frame-steps">
            {steps} {steps === 1 ? "step" : "steps"}
          </span>
          <span className="node-card-status">
            {status.map((s) => (
              <span key={s.tone} className={`badge ${s.tone}`} title={s.title}>
                {s.label}
              </span>
            ))}
          </span>
        </div>
        {heat ? (
          <HeatLines heat={heat} />
        ) : (
          <div className="node-card-task" title={stage.nodes.join(", ")}>
            {stage.nodes.map((name, i) => (
              <Fragment key={name}>
                {i > 0 && " · "}
                <span className={name === activeStep ? "stage-card-active-step" : undefined}>{displayName(name)}</span>
              </Fragment>
            ))}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
});
