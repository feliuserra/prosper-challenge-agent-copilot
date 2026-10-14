import dagre from "@dagrejs/dagre";

import type { Agent, Edge, Position } from "./schema";

// Canvas positions (`ui`) for nodes that have none. A full dagre layout runs only
// when no node has a position; otherwise missing nodes are placed one by one and
// existing nodes never move (ADR 0002).

/** Card width on the canvas; the node card uses it too, so layout and render agree. */
export const NODE_WIDTH = 240;
/** Approximate card height (name line + task line). Only used for spacing. */
export const NODE_HEIGHT = 64;
const NODE_GAP = 60;
// Room between a card and the next rank's cards, with an edge label in the middle.
const RANK_GAP = 120;

// Edge labels (FunctionEdge, `.edge-label`). Longer text is cut with an ellipsis.
export const LABEL_HEIGHT = 24;
export const LABEL_MAX_WIDTH = 260;
// Space between the labels of a branch.
const LABEL_GAP = 20;

/**
 * What an edge's label says: its description on one line, without the "Call"
 * of "Call when ..." that descriptions for the model start with, so labels
 * differ early; or its function name when it has no description.
 */
export function edgeLabel(edge: Edge): string {
  const text = edge.description
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^call (?=(when|once|if|after|as soon as) )/i, "");
  return text ? text[0].toUpperCase() + text.slice(1) : edge.function;
}

/** A label's approximate width: 12px sans-serif text, the icon and padding, up to the maximum. */
export const labelWidth = (text: string) => Math.min(text.length * 6.5 + 38, LABEL_MAX_WIDTH);

const round = ({ x, y }: Position): Position => ({ x: Math.round(x), y: Math.round(y) });

/**
 * The width each node takes in its rank. A label sits halfway between its two
 * cards (edgePath.ts), so labels of edges out of one node are half as far apart
 * as their targets: the targets of a branch take twice their label's width, less
 * the gap between cards, which leaves LABEL_GAP between neighbouring labels.
 */
function slotWidths(agent: Agent): Map<string, number> {
  const widths = new Map(agent.nodes.map((n) => [n.name, NODE_WIDTH]));
  for (const node of agent.nodes) {
    const out = (node.edges ?? []).filter((e) => e.target !== node.name && widths.has(e.target));
    if (new Set(out.map((e) => e.target)).size < 2) continue;
    for (const edge of out) {
      const width = 2 * labelWidth(edgeLabel(edge)) + 2 * LABEL_GAP - NODE_GAP;
      widths.set(edge.target, Math.max(widths.get(edge.target)!, width));
    }
  }
  return widths;
}

/** A full top-to-bottom layout: every node gets a new position. */
export function autoLayout(agent: Agent): Agent {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({ rankdir: "TB", nodesep: NODE_GAP, ranksep: RANK_GAP });
  graph.setDefaultEdgeLabel(() => ({}));
  // A card is centred in its slot: positions come from the centre below.
  for (const [name, width] of slotWidths(agent)) graph.setNode(name, { width, height: NODE_HEIGHT });
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
