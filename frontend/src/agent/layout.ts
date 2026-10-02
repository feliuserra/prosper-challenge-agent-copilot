import dagre from "@dagrejs/dagre";

import type { Agent, Position } from "./schema";

// Canvas positions (`ui`) for nodes that have none. A full dagre layout runs only
// when no node has a position; otherwise missing nodes are placed one by one and
// existing nodes never move (ADR 0002).

/** Card width on the canvas; the node card uses it too, so layout and render agree. */
export const NODE_WIDTH = 240;
/** Approximate card height (name line + task line). Only used for spacing. */
export const NODE_HEIGHT = 64;
const NODE_GAP = 60;
// Room between ranks for an edge's function-name label.
const RANK_GAP = 90;

const round = ({ x, y }: Position): Position => ({ x: Math.round(x), y: Math.round(y) });

/** A full top-to-bottom layout: every node gets a new position. */
export function autoLayout(agent: Agent): Agent {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "TB", nodesep: NODE_GAP, ranksep: RANK_GAP });
  graph.setDefaultEdgeLabel(() => ({}));
  for (const node of agent.nodes) graph.setNode(node.name, { width: NODE_WIDTH, height: NODE_HEIGHT });
  for (const node of agent.nodes) {
    for (const edge of node.edges ?? []) {
      if (graph.hasNode(edge.target)) graph.setEdge(node.name, edge.target);
    }
  }
  dagre.layout(graph);
  return {
    ...agent,
    nodes: agent.nodes.map((node) => {
      // dagre gives the centre; React Flow positions are the top-left corner.
      const { x, y } = graph.node(node.name);
      return { ...node, ui: { ...node.ui, ...round({ x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 }) } };
    }),
  };
}

export type Rect = { x: number; y: number; width: number; height: number };

/** Whether a card at `p` would touch a card at any of `taken` (with a small margin). */
function overlaps(p: Position, taken: Position[]): boolean {
  return taken.some(
    (q) => Math.abs(q.x - p.x) < NODE_WIDTH + NODE_GAP / 2 && Math.abs(q.y - p.y) < NODE_HEIGHT + NODE_GAP / 2,
  );
}

/** `start`, or the first spot to its right that does not overlap a node in `taken`. */
export function freeSpot(start: Position, taken: Iterable<Position>): Position {
  const others = [...taken];
  let spot = round(start);
  while (overlaps(spot, others)) spot = { x: spot.x + NODE_WIDTH + NODE_GAP, y: spot.y };
  return spot;
}

/**
 * The free spot closest to `start` for a card that fits entirely inside `area`
 * (e.g. the visible part of the canvas), or `start` itself when there is none.
 */
export function nearestFreeSpot(start: Position, taken: Iterable<Position>, area: Rect): Position {
  const others = [...taken];
  if (!overlaps(start, others)) return round(start);
  const step = 20;
  let best: Position | null = null;
  let bestDistance = Infinity;
  for (let x = area.x; x + NODE_WIDTH <= area.x + area.width; x += step) {
    for (let y = area.y; y + NODE_HEIGHT <= area.y + area.height; y += step) {
      const distance = Math.hypot(x - start.x, y - start.y);
      if (distance < bestDistance && !overlaps({ x, y }, others)) {
        best = { x, y };
        bestDistance = distance;
      }
    }
  }
  return round(best ?? start);
}

/**
 * Give each node without a position one, leaving positioned nodes where they are:
 * one rank below a positioned node that has an edge to it, otherwise at `fallback`
 * (default: below everything). Returns `agent` itself when nothing is missing.
 */
export function placeMissing(agent: Agent, fallback?: Position): Agent {
  const placed = new Map<string, Position>();
  for (const node of agent.nodes) if (node.ui) placed.set(node.name, node.ui);
  const pending = agent.nodes.filter((n) => !n.ui).map((n) => n.name);
  if (!pending.length) return agent;

  const sourceOf = (name: string) =>
    agent.nodes.find((n) => placed.has(n.name) && (n.edges ?? []).some((e) => e.target === name));
  const below = () => {
    const all = [...placed.values()];
    if (!all.length) return { x: 0, y: 0 };
    return { x: Math.min(...all.map((p) => p.x)), y: Math.max(...all.map((p) => p.y)) + NODE_HEIGHT + RANK_GAP };
  };

  // Nodes reachable from a placed node first, so chains follow their sources.
  while (pending.length) {
    const index = Math.max(
      0,
      pending.findIndex((name) => sourceOf(name)),
    );
    const [name] = pending.splice(index, 1);
    const source = sourceOf(name);
    const start = source
      ? { x: placed.get(source.name)!.x, y: placed.get(source.name)!.y + NODE_HEIGHT + RANK_GAP }
      : (fallback ?? below());
    placed.set(name, freeSpot(start, placed.values()));
  }
  return {
    ...agent,
    nodes: agent.nodes.map((n) => (n.ui ? n : { ...n, ui: placed.get(n.name)! })),
  };
}

/** Positions for an agent being opened: a full layout if it has none, else fill the gaps. */
export function withPositions(agent: Agent): Agent {
  return agent.nodes.some((n) => n.ui) ? placeMissing(agent) : autoLayout(agent);
}
