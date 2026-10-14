import dagre from "@dagrejs/dagre";

import type { Agent, Edge, Node, Position } from "./schema";
import { stagesOf } from "./stages";

// Canvas positions (`ui`) for nodes that have none. A full dagre layout runs only
// when no node has a position; otherwise missing nodes are placed one by one and
// existing nodes never move (ADR 0002).

// Card sizes; the node card (NodeCard, `.node-card`) uses them too, so layout and render agree.
export const NODE_WIDTH = 360;
/** A card's height: its name and two lines of task. */
export const NODE_HEIGHT = 98;
/** The tools footer under a card with tools. */
const TOOLS_HEIGHT = 41;
const TALLEST_CARD = NODE_HEIGHT + TOOLS_HEIGHT;
export const cardHeight = (node: Node) => NODE_HEIGHT + (node.tools?.length ? TOOLS_HEIGHT : 0);
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

/**
 * A full top-to-bottom layout: every node gets a new position. The nodes of a
 * stage are laid out as one block (a dagre cluster), so stage frames do not
 * overlap; dagre leaves an extra rank gap between blocks.
 */
export function autoLayout(agent: Agent): Agent {
  const graph = new dagre.graphlib.Graph({ compound: true });
  graph.setGraph({ rankdir: "TB", nodesep: NODE_GAP, ranksep: RANK_GAP });
  graph.setDefaultEdgeLabel(() => ({}));
  // dagre ids of our own: node names can be any text, so they could clash with a stage's id.
  const ids = new Map(agent.nodes.map((n, i) => [n.name, `node${i}`]));
  // A card is centred in its slot: positions come from the centre below.
  const widths = slotWidths(agent);
  for (const node of agent.nodes) {
    graph.setNode(ids.get(node.name)!, { width: widths.get(node.name)!, height: cardHeight(node) });
  }
  stagesOf(agent).forEach((stage, i) => {
    graph.setNode(`stage${i}`, {});
    for (const name of stage.nodes) graph.setParent(ids.get(name)!, `stage${i}`);
  });
  for (const node of agent.nodes) {
    for (const edge of node.edges ?? []) {
      const target = ids.get(edge.target);
      if (target) graph.setEdge(ids.get(node.name)!, target);
    }
  }
  dagre.layout(graph);
  return {
    ...agent,
    nodes: agent.nodes.map((node) => {
      // dagre gives the centre; React Flow positions are the top-left corner.
      const { x, y } = graph.node(ids.get(node.name)!);
      return { ...node, ui: { ...node.ui, ...round({ x: x - NODE_WIDTH / 2, y: y - cardHeight(node) / 2 }) } };
    }),
  };
}

export type Rect = { x: number; y: number; width: number; height: number };

/** Whether a card at `p` would touch a card at any of `taken` (with a small margin), either having tools. */
function overlaps(p: Position, taken: Position[]): boolean {
  return taken.some(
    (q) => Math.abs(q.x - p.x) < NODE_WIDTH + NODE_GAP / 2 && Math.abs(q.y - p.y) < TALLEST_CARD + NODE_GAP / 2,
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
  const bottom = (node: Node) => placed.get(node.name)!.y + cardHeight(node);
  const below = () => {
    const all = agent.nodes.filter((n) => placed.has(n.name));
    if (!all.length) return { x: 0, y: 0 };
    return { x: Math.min(...all.map((n) => placed.get(n.name)!.x)), y: Math.max(...all.map(bottom)) + RANK_GAP };
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
      ? { x: placed.get(source.name)!.x, y: bottom(source) + RANK_GAP }
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
