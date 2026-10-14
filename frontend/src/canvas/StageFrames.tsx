import { ViewportPortal } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import type { StageFrame } from "./derive";

/**
 * A tinted frame behind each stage's cards (#50), drawn in the viewport under
 * the edges and cards. Only its label takes clicks: it selects the stage.
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
          <button
            className="stage-frame-label nodrag nopan"
            onClick={() => useAgentStore.getState().select({ kind: "stage", name: frame.name })}
          >
            {frame.name}
            <span className="stage-frame-steps">
              {frame.nodes.length} {frame.nodes.length === 1 ? "step" : "steps"}
            </span>
          </button>
        </div>
      ))}
    </ViewportPortal>
  );
}
