import { ViewportPortal } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import type { StageFrame } from "./derive";
import { Chevron } from "./StageCard";

const store = () => useAgentStore.getState();

/**
 * A tinted frame behind each expanded stage's cards (#50), drawn in the viewport
 * under the edges and cards. Only its header takes clicks: the chevron collapses
 * the stage (#51) and the label selects it.
 */
export function StageFrames({ frames, selected }: { frames: StageFrame[]; selected: string | null }) {
  return (
    <ViewportPortal>
      {frames.map((frame) => (
        <div
          key={frame.name}
          className={`stage-frame tone-${frame.tone}${frame.name === selected ? " selected" : ""}`}
          style={{ width: frame.width, height: frame.height, transform: `translate(${frame.x}px, ${frame.y}px)` }}
        >
          <div className="stage-frame-header nodrag nopan">
            <button
              className="stage-frame-toggle"
              title="Collapse the stage into one card"
              aria-label={`Collapse ${frame.name}`}
              onClick={() => store().setCollapsed(frame.name, true)}
            >
              <Chevron open />
            </button>
            <button className="stage-frame-label" onClick={() => store().select({ kind: "stage", name: frame.name })}>
              {frame.name}
              <span className="stage-frame-steps">
                {frame.nodes.length} {frame.nodes.length === 1 ? "step" : "steps"}
              </span>
            </button>
          </div>
        </div>
      ))}
    </ViewportPortal>
  );
}
