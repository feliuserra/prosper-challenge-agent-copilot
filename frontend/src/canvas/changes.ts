import type { EdgeChange, NodeChange } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import { parseEdgeId, type AgentFlowEdge, type AgentFlowNode, type Dimensions } from "./derive";

// React Flow reports what the user did as change lists; each one becomes a store
// operation, so no graph state lives only in React Flow (ADR 0001). Removals are
// not handled here: the canvas deletes through `onDelete`, where it sees the whole
// deletion at once and can skip edges that `deleteNode` already removes.

const store = () => useAgentStore.getState();
const history = () => useAgentStore.temporal.getState();

export function handleNodeChanges(
  changes: NodeChange<AgentFlowNode>[],
  onMeasured: (name: string, dimensions: Dimensions) => void,
) {
  let dragEnded = false;
  for (const change of changes) {
    if (change.type === "position" && change.position) {
      const { x, y } = change.position;
      store().moveNode(change.id, { x: Math.round(x), y: Math.round(y) });
      // One drag, one undo step. Positions are written on every frame; the first
      // write of a drag is recorded (its "before" is the agent before the drag)
      // and history is paused for the rest. Pausing before that first write would
      // leave the drag with no history entry at all.
      if (change.dragging && history().isTracking) history().pause();
      // The last changes of a drag (also of an aborted one) have dragging: false.
      if (change.dragging === false) dragEnded = true;
    } else if (change.type === "dimensions" && change.dimensions) {
      onMeasured(change.id, change.dimensions);
    } else if (change.type === "select") {
      const { selection } = store();
      if (change.selected) store().select({ kind: "node", name: change.id });
      else if (selection?.kind === "node" && selection.name === change.id) store().select(null);
    }
  }
  // After the whole batch: a multi-node drag ends with one change per node.
  if (dragEnded) history().resume();
}

export function handleEdgeChanges(changes: EdgeChange<AgentFlowEdge>[]) {
  for (const change of changes) {
    if (change.type !== "select") continue;
    const { source, function: fn } = parseEdgeId(change.id);
    const { selection } = store();
    if (change.selected) store().select({ kind: "edge", source, function: fn });
    else if (selection?.kind === "edge" && selection.source === source && selection.function === fn) {
      store().select(null);
    }
  }
}
