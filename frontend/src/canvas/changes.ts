import type { Connection, EdgeChange, NodeChange } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import { parseEdgeId, type CanvasFlowEdge, type CanvasFlowNode, type Dimensions } from "./derive";
import { flatView, type CanvasView } from "./view";

// React Flow reports what the user did as change lists and callbacks; each one
// becomes a store operation, so no graph state lives only in React Flow (ADR 0001).
// Removals are not change lists here: the canvas deletes through `onDelete`
// (`deleteElements`), where it sees the whole deletion at once and can skip edges
// that `deleteNode` already removes. Collapsed stages' cards and the Start and End
// pills are not nodes of the agent: pills never reach the store, and cards only
// through their stage.

const store = () => useAgentStore.getState();
const history = () => useAgentStore.temporal.getState();

/** Whether `id` is one of the agent's nodes, not a stage's card or a pill. */
const isAgentNode = (id: string, view: CanvasView) => !view.cardStage.has(id) && !view.terminals.has(id);
const isPillEdge = (id: string, view: CanvasView) => [...view.terminals.values()].some((t) => t.edgeId === id);

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
    // Pills are only measured; React Flow cannot move or select them, so this is a guard.
    if ("id" in change && view.terminals.has(change.id) && change.type !== "dimensions") continue;
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

export function handleEdgeChanges(changes: EdgeChange<CanvasFlowEdge>[], view: CanvasView = flatView) {
  for (const change of changes) {
    if (change.type !== "select" || isPillEdge(change.id, view)) continue;
    const { source, function: fn } = parseEdgeId(change.id);
    const { selection } = store();
    if (change.selected) store().select({ kind: "edge", source, function: fn });
    else if (selection?.kind === "edge" && selection.source === source && selection.function === fn) {
      store().select(null);
    }
  }
}

/** A connection dragged between two handles. Edges join nodes; cards and pills do not connect, so this is a guard. */
export function connectNodes({ source, target }: Connection, view: CanvasView = flatView) {
  if (isAgentNode(source, view) && isAgentNode(target, view)) store().connect(source, target);
}

/** The selected edge's arrowhead dropped on another node. */
export function reconnectEdge(edge: CanvasFlowEdge, { source, target }: Connection, view: CanvasView = flatView) {
  if (edge.type !== "function" || !edge.data) return;
  if (source !== edge.source || target === edge.target || !isAgentNode(target, view)) return;
  // By the edge's id: `edge.source` is a card when the edge leaves a collapsed stage.
  store().updateEdge(parseEdgeId(edge.id).source, edge.data.function, { target });
}

/**
 * What React Flow deleted (Backspace or Delete), as one batch. Returns the store's
 * refusals. Cards and pills are not deletable, and only nodes and function edges
 * are deleted here, so that is a guard too.
 */
export function deleteElements({ nodes, edges }: { nodes: CanvasFlowNode[]; edges: CanvasFlowEdge[] }): string[] {
  const deleted = new Set(nodes.filter((n) => n.type === "agent").map((n) => n.id));
  const errors: string[] = [];
  for (const name of deleted) {
    const result = store().deleteNode(name);
    if (!result.ok) errors.push(result.error);
  }
  // Edges into or out of a deleted node went with it (deleteNode cascades).
  for (const edge of edges) {
    if (edge.type !== "function") continue;
    const { source, function: fn } = parseEdgeId(edge.id);
    if (!deleted.has(source) && !deleted.has(edge.target)) store().deleteEdge(source, fn);
  }
  return errors;
}
