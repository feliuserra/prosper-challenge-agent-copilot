import type { EdgeChange, NodeChange } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import { parseEdgeId, type AgentFlowEdge, type CanvasFlowNode, type Dimensions } from "./derive";
import { flatView, type CanvasView } from "./view";

// React Flow reports what the user did as change lists; each one becomes a store
// operation, so no graph state lives only in React Flow (ADR 0001). Removals are
// not handled here: the canvas deletes through `onDelete`, where it sees the whole
// deletion at once and can skip edges that `deleteNode` already removes.

const store = () => useAgentStore.getState();
const history = () => useAgentStore.temporal.getState();

/**
 * `view` is what the canvas shows (view.ts): a collapsed stage's card moves all
 * its nodes, and a dragged node's position is stored as if no stage were collapsed.
 */
export function handleNodeChanges(
  changes: NodeChange<CanvasFlowNode>[],
  onMeasured: (id: string, dimensions: Dimensions) => void,
  view: CanvasView = flatView,
) {
  let dragEnded = false;
  for (const change of changes) {
    const stage = "id" in change ? view.cardStage.get(change.id) : undefined;
    if (change.type === "position" && change.position) {
      const position = { x: Math.round(change.position.x), y: Math.round(change.position.y) };
      if (stage === undefined) store().moveNode(change.id, view.stored(position));
      else {
        const card = view.cards.get(stage)!.position;
        store().moveStage(stage, { x: position.x - card.x, y: position.y - card.y });
      }
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
      const selects =
        stage === undefined ? ({ kind: "node", name: change.id } as const) : ({ kind: "stage", name: stage } as const);
      if (change.selected) store().select(selects);
      else if (selection?.kind === selects.kind && selection.name === selects.name) store().select(null);
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
