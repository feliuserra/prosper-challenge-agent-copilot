import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

import { TERMINAL_WIDTH } from "../agent/layout";
import type { TerminalFlowNode } from "./derive";

/** A flag on a pole: where a call starts. */
function FlagIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 21V4" />
        <path d="M5 4h11l-2 4 2 4H5" fill="currentColor" fillOpacity="0.2" />
      </g>
    </svg>
  );
}

/** A handset tipped down: the call hangs up. */
function HangUpIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path
        d="M3.5 14.5c-.6-.6-.6-1.6.1-2.2C8.2 8.4 15.8 8.4 20.4 12.3c.7.6.7 1.6.1 2.2l-1.6 1.6c-.5.5-1.3.6-1.9.2l-2.1-1.4c-.4-.3-.6-.7-.6-1.2v-1.4a12 12 0 0 0-4.6 0v1.4c0 .5-.2.9-.6 1.2l-2.1 1.4c-.6.4-1.4.3-1.9-.2Z"
        fill="currentColor"
      />
    </svg>
  );
}

/**
 * The Start pill above the start node, or an End pill below an end node (#47).
 * Derived from the agent, never stored: it cannot be selected, moved, deleted or
 * connected, and its handles only anchor its plain edge.
 */
export const TerminalNode = memo(function TerminalNode({ data }: NodeProps<TerminalFlowNode>) {
  const start = data.kind === "start";
  return (
    <div
      className={`terminal-node ${data.kind}`}
      style={{ width: TERMINAL_WIDTH }}
      title={start ? "Calls start here" : "The call ends after this step"}
    >
      {start ? <FlagIcon /> : <HangUpIcon />}
      {start ? "Start" : "End"}
      <Handle type={start ? "source" : "target"} position={start ? Position.Bottom : Position.Top} isConnectable={false} />
    </div>
  );
});
