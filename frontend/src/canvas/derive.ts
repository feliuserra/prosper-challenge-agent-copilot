import { MarkerType, type Edge as FlowEdge, type Node as FlowNode } from "@xyflow/react";

import type { Agent, Node } from "../agent/schema";
import type { Selection } from "../store/agentStore";

// React Flow nodes and edges are derived from the agent on every change (ADR 0001).
// Node id = node name; edge id = `${source}::${function}` (unique: the store never
// holds two edges with the same function name in one node).

/** A badge in the node card's status slot (validation errors #6, warnings #9). */
export type NodeStatus = { tone: "error" | "warning"; label: string; title?: string };

export type AgentNodeData = { node: Node; isStart: boolean; status?: NodeStatus[] };
export type AgentFlowNode = FlowNode<AgentNodeData, "agent">;

/** `lane` separates edges that join the same two nodes (see edgePath.ts). */
export type FunctionEdgeData = { function: string; lane: number };
export type AgentFlowEdge = FlowEdge<FunctionEdgeData, "function">;

export type Dimensions = { width: number; height: number };

export const edgeId = (source: string, fn: string) => `${source}::${fn}`;

/** Inverse of `edgeId`. Function names cannot contain ':', so the last "::" splits. */
export function parseEdgeId(id: string): { source: string; function: string } {
  const at = id.lastIndexOf("::");
  return { source: id.slice(0, at), function: id.slice(at + 2) };
}

/**
 * `measured` holds the card sizes React Flow reported. They are DOM measurements,
 * not graph state, but a controlled React Flow needs them back on its nodes.
 */
export function toFlowNodes(
  agent: Agent,
  selection: Selection,
  measured: Record<string, Dimensions> = {},
): AgentFlowNode[] {
  return agent.nodes.map((node) => ({
    id: node.name,
    type: "agent",
    // The store gives every node a position (open, addNode); 0,0 is only a guard.
    position: { x: node.ui?.x ?? 0, y: node.ui?.y ?? 0 },
    data: { node, isStart: node.name === agent.initial_node },
    selected: selection?.kind === "node" && selection.name === node.name,
    measured: measured[node.name],
  }));
}

export function toFlowEdges(agent: Agent, selection: Selection): AgentFlowEdge[] {
  const names = new Set(agent.nodes.map((n) => n.name));
  // Edges to a missing node cannot be drawn; validation (#6) reports them.
  const drawn = agent.nodes.flatMap((node) =>
    (node.edges ?? []).filter((e) => names.has(e.target)).map((edge) => ({ source: node.name, edge })),
  );

  const pairCount = new Map<string, number>();
  for (const { source, edge } of drawn) {
    const pair = `${source}->${edge.target}`;
    pairCount.set(pair, (pairCount.get(pair) ?? 0) + 1);
  }
  const pairIndex = new Map<string, number>();

  return drawn.map(({ source, edge }) => {
    const pair = `${source}->${edge.target}`;
    const index = pairIndex.get(pair) ?? 0;
    pairIndex.set(pair, index + 1);
    const selected = selection?.kind === "edge" && selection.source === source && selection.function === edge.function;
    return {
      id: edgeId(source, edge.function),
      type: "function",
      source,
      target: edge.target,
      data: { function: edge.function, lane: index - (pairCount.get(pair)! - 1) / 2 },
      selected,
      // Only the selected edge shows a reconnect knob, so it is clear which edge
      // moves when several end at the same handle. Only the target end: moving
      // the source would move the edge into another node's function list.
      reconnectable: selected ? "target" : false,
      markerEnd: { type: MarkerType.ArrowClosed },
    };
  });
}
