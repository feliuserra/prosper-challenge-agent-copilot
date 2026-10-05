import { MarkerType, type Edge as FlowEdge, type Node as FlowNode } from "@xyflow/react";

import { NODE_HEIGHT, NODE_WIDTH } from "../agent/layout";
import type { Agent, Node } from "../agent/schema";
import type { Selection } from "../store/agentStore";
import type { Problem, Severity } from "../validation/problems";
import { routeBackEdges, type BackRoute, type Box } from "./edgePath";

// React Flow nodes and edges are derived from the agent on every change (ADR 0001).
// Node id = node name; edge id = `${source}::${function}` (unique: the store never
// holds two edges with the same function name in one node).

/** A badge on a node card or an edge label: validation errors (#6), warnings (#9). */
export type StatusBadge = { tone: Severity; label: string; title: string };

/** `active`: the node a test call is in (#8). */
export type AgentNodeData = { node: Node; isStart: boolean; status?: StatusBadge[]; active?: boolean };
export type AgentFlowNode = FlowNode<AgentNodeData, "agent">;

/**
 * `lane` separates edges that join the same two nodes (see edgePath.ts).
 * `route`: set for a back edge (into a node above), the column it runs up.
 * `active`: the edge a test call took last (#8).
 */
export type FunctionEdgeData = {
  function: string;
  lane: number;
  route?: BackRoute;
  status?: StatusBadge[];
  active?: boolean;
};
export type AgentFlowEdge = FlowEdge<FunctionEdgeData, "function">;

export type Dimensions = { width: number; height: number };

export const edgeId = (source: string, fn: string) => `${source}::${fn}`;

/** Inverse of `edgeId`. Function names cannot contain ':', so the last "::" splits. */
export function parseEdgeId(id: string): { source: string; function: string } {
  const at = id.lastIndexOf("::");
  return { source: id.slice(0, at), function: id.slice(at + 2) };
}

/** Badges by node name and by edge id. */
export type StatusBadges = { nodes: Map<string, StatusBadge[]>; edges: Map<string, StatusBadge[]> };

/** Edges that can be drawn: those whose target node exists. */
function drawnEdges(agent: Agent) {
  const names = new Set(agent.nodes.map((n) => n.name));
  return agent.nodes.flatMap((node) =>
    (node.edges ?? []).filter((e) => names.has(e.target)).map((edge) => ({ source: node.name, edge })),
  );
}

/**
 * One badge per severity for each node and edge with problems, e.g. "2 errors",
 * with the messages as its tooltip. Problems are matched by their `node` and
 * `edge` fields. A problem of an edge that is not drawn (its target is missing)
 * goes on the edge's node, so it is still visible on the canvas. Agent-level
 * problems have no badge; the problems list shows them.
 */
export function statusBadges(agent: Agent, problems: Problem[]): StatusBadges {
  const names = new Set(agent.nodes.map((n) => n.name));
  const drawn = new Set(drawnEdges(agent).map(({ source, edge }) => edgeId(source, edge.function)));
  const onNodes = new Map<string, Problem[]>();
  const onEdges = new Map<string, Problem[]>();
  const add = (map: Map<string, Problem[]>, key: string, problem: Problem) =>
    map.set(key, [...(map.get(key) ?? []), problem]);

  for (const problem of problems) {
    const { node, edge } = problem;
    if (node === null || !names.has(node)) continue;
    const id = edge === null ? null : edgeId(node, edge);
    if (id !== null && drawn.has(id)) add(onEdges, id, problem);
    // On the node, say which edge the problem is about.
    else add(onNodes, node, edge === null ? problem : { ...problem, message: `${edge}: ${problem.message}` });
  }
  const badges = (map: Map<string, Problem[]>) =>
    new Map([...map].map(([key, list]) => [key, toBadges(list)] as const));
  return { nodes: badges(onNodes), edges: badges(onEdges) };
}

function toBadges(problems: Problem[]): StatusBadge[] {
  return (["error", "warning"] as const).flatMap((tone) => {
    const messages = problems.filter((p) => p.severity === tone).map((p) => p.message);
    if (!messages.length) return [];
    const label = `${messages.length} ${tone}${messages.length === 1 ? "" : "s"}`;
    return [{ tone, label, title: messages.join("\n") }];
  });
}

/**
 * `measured` holds the card sizes React Flow reported. They are DOM measurements,
 * not graph state, but a controlled React Flow needs them back on its nodes.
 */
export function toFlowNodes(
  agent: Agent,
  selection: Selection,
  measured: Record<string, Dimensions> = {},
  status: Map<string, StatusBadge[]> = new Map(),
  activeNode: string | null = null,
): AgentFlowNode[] {
  return agent.nodes.map((node) => ({
    id: node.name,
    type: "agent",
    // The store gives every node a position (open, addNode); 0,0 is only a guard.
    position: { x: node.ui?.x ?? 0, y: node.ui?.y ?? 0 },
    data: {
      node,
      isStart: node.name === agent.initial_node,
      status: status.get(node.name),
      active: node.name === activeNode,
    },
    selected: selection?.kind === "node" && selection.name === node.name,
    measured: measured[node.name],
  }));
}

export function toFlowEdges(
  agent: Agent,
  selection: Selection,
  status: Map<string, StatusBadge[]> = new Map(),
  activeEdge: string | null = null,
  measured: Record<string, Dimensions> = {},
): AgentFlowEdge[] {
  // Edges to a missing node cannot be drawn; validation reports them on their node.
  const drawn = drawnEdges(agent);

  const boxes = new Map<string, Box>(
    agent.nodes.map((n) => [
      n.name,
      {
        x: n.ui?.x ?? 0,
        y: n.ui?.y ?? 0,
        width: measured[n.name]?.width ?? NODE_WIDTH,
        height: measured[n.name]?.height ?? NODE_HEIGHT,
      },
    ]),
  );
  const routes = routeBackEdges(
    boxes,
    drawn.map(({ source, edge }) => ({
      id: edgeId(source, edge.function),
      source,
      target: edge.target,
      label: edge.function,
    })),
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
    const id = edgeId(source, edge.function);
    const active = id === activeEdge;
    return {
      id,
      type: "function",
      source,
      target: edge.target,
      data: {
        function: edge.function,
        lane: index - (pairCount.get(pair)! - 1) / 2,
        route: routes.get(id),
        status: status.get(id),
        active,
      },
      selected,
      animated: active,
      // Only the selected edge shows a reconnect knob, so it is clear which edge
      // moves when several end at the same handle. Only the target end: moving
      // the source would move the edge into another node's function list.
      reconnectable: selected ? "target" : false,
      markerEnd: { type: MarkerType.ArrowClosed },
    };
  });
}
