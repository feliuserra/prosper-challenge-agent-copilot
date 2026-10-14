import { MarkerType, type Edge as FlowEdge, type Node as FlowNode } from "@xyflow/react";

import {
  cardHeight,
  edgeLabel,
  NODE_HEIGHT,
  NODE_WIDTH,
  TERMINAL_GAP,
  TERMINAL_HEIGHT,
  TERMINAL_WIDTH,
} from "../agent/layout";
import type { Agent, Node } from "../agent/schema";
import { stageOf, stagesOf, type Stage } from "../agent/stages";
import type { Selection } from "../store/agentStore";
import type { Problem, Severity } from "../validation/problems";
import { routeBackEdges, type BackRoute, type Box } from "./edgePath";
import { canvasView, type CanvasView, type Dimensions, type Terminal } from "./view";

// React Flow nodes and edges are derived from the agent on every change (ADR 0001).
// Node id = node name; edge id = `${source}::${function}` (unique: the store never
// holds two edges with the same function name in one node). With collapsed stages
// (#51, view.ts), a stage's card stands in for its nodes: edges into and out of the
// stage end at the card, and edges inside it are not drawn. The Start and End pills
// (#47) and their plain edges are derived too, and never reach the store.

/** A badge on a node card or an edge label: validation errors (#6), warnings (#9). */
export type StatusBadge = { tone: Severity; label: string; title: string };

/** `active`: the node a test call is in (#8). */
export type AgentNodeData = { node: Node; status?: StatusBadge[]; active?: boolean };
export type AgentFlowNode = FlowNode<AgentNodeData, "agent">;

/** A collapsed stage's card. `activeStep`: the node in it a test call is in. */
export type StageCardData = { stage: Stage; status?: StatusBadge[]; activeStep: string | null };
export type StageFlowNode = FlowNode<StageCardData, "stage">;

/** A Start or End pill (#47): where a call starts, and where it can end. */
export type TerminalData = { kind: Terminal["kind"] };
export type TerminalFlowNode = FlowNode<TerminalData, "terminal">;
export type CanvasFlowNode = AgentFlowNode | StageFlowNode | TerminalFlowNode;

/**
 * `label`: what the edge's label says (`edgeLabel`).
 * `lane` separates edges that join the same two nodes (see edgePath.ts).
 * `route`: set for a back edge (into a node above), the column it runs up.
 * `active`: the edge a test call took last (#8).
 */
export type FunctionEdgeData = {
  function: string;
  label: string;
  lane: number;
  route?: BackRoute;
  status?: StatusBadge[];
  active?: boolean;
};
export type AgentFlowEdge = FlowEdge<FunctionEdgeData, "function">;
/** The plain edge from the Start pill to its card, or from a card to its End pill. */
export type TerminalFlowEdge = FlowEdge<Record<string, never>, "default">;
export type CanvasFlowEdge = AgentFlowEdge | TerminalFlowEdge;

export type { Dimensions };

// Edge colours, as in index.css. Arrowheads are shared SVG markers, so CSS cannot
// colour them per edge; each colour gets its own marker.
const EDGE_STROKE = "#b6bcc4";
const SELECTED_STROKE = "#0969da";
const ACTIVE_STROKE = "#1a7f37";

export const edgeId = (source: string, fn: string) => `${source}::${fn}`;

/** Inverse of `edgeId`. Function names cannot contain ':', so the last "::" splits. */
export function parseEdgeId(id: string): { source: string; function: string } {
  const at = id.lastIndexOf("::");
  return { source: id.slice(0, at), function: id.slice(at + 2) };
}

/** Badges by node name (or collapsed stage card id) and by edge id. */
export type StatusBadges = { nodes: Map<string, StatusBadge[]>; edges: Map<string, StatusBadge[]> };

/** Edges that are drawn: those whose target node exists, except edges inside a collapsed stage. */
function drawnEdges(agent: Agent, view: CanvasView) {
  const names = new Set(agent.nodes.map((n) => n.name));
  const inside = (source: string, target: string) =>
    view.hiddenIn.has(source) && view.hiddenIn.get(source) === view.hiddenIn.get(target);
  return agent.nodes.flatMap((node) =>
    (node.edges ?? [])
      .filter((e) => names.has(e.target) && !inside(node.name, e.target))
      .map((edge) => ({ source: node.name, edge })),
  );
}

/**
 * One badge per severity for each node and edge with problems, e.g. "2 errors",
 * with the messages as its tooltip. Problems are matched by their `node` and
 * `edge` fields. A problem of an edge that is not drawn (its target is missing)
 * goes on the edge's node, so it is still visible on the canvas. Problems of a
 * node in a collapsed stage, and of edges inside it, go on the stage's card.
 * Agent-level problems have no badge; the problems list shows them.
 */
export function statusBadges(
  agent: Agent,
  problems: Problem[],
  view: CanvasView = canvasView(agent, []),
): StatusBadges {
  const names = new Set(agent.nodes.map((n) => n.name));
  const drawn = new Set(drawnEdges(agent, view).map(({ source, edge }) => edgeId(source, edge.function)));
  const onNodes = new Map<string, Problem[]>();
  const onEdges = new Map<string, Problem[]>();
  const add = (map: Map<string, Problem[]>, key: string, problem: Problem) =>
    map.set(key, [...(map.get(key) ?? []), problem]);

  for (const problem of problems) {
    const { node, edge } = problem;
    if (node === null || !names.has(node)) continue;
    const id = edge === null ? null : edgeId(node, edge);
    if (id !== null && drawn.has(id)) add(onEdges, id, problem);
    else {
      // On the node, say which edge the problem is about; on a stage's card, which node too.
      const where = [view.hiddenIn.has(node) ? node : null, edge].filter((part) => part !== null).join(" › ");
      add(onNodes, view.endOf(node), where ? { ...problem, message: `${where}: ${problem.message}` } : problem);
    }
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
 * Nodes in collapsed stages are left out; each collapsed stage is one card. The
 * Start and End pills come last.
 */
export function toFlowNodes(
  agent: Agent,
  selection: Selection,
  measured: Record<string, Dimensions> = {},
  status: Map<string, StatusBadge[]> = new Map(),
  activeNode: string | null = null,
  view: CanvasView = canvasView(agent, [], measured),
): CanvasFlowNode[] {
  const nodes: CanvasFlowNode[] = agent.nodes
    .filter((node) => !view.hiddenIn.has(node.name))
    .map((node) => ({
      id: node.name,
      type: "agent",
      // The store gives every node a position (open, addNode); 0,0 is only a guard.
      position: view.shown(node),
      data: { node, status: status.get(node.name), active: node.name === activeNode },
      selected: selection?.kind === "node" && selection.name === node.name,
      measured: measured[node.name],
    }));
  const cards: CanvasFlowNode[] = [...view.cards.values()].map(({ id, stage, position }) => ({
    id,
    type: "stage",
    position,
    data: {
      stage,
      status: status.get(id),
      activeStep: activeNode !== null && stage.nodes.includes(activeNode) ? activeNode : null,
    },
    selected: selection?.kind === "stage" && selection.name === stage.name,
    measured: measured[id],
    // Edges end at a card, but new edges must join nodes, and deleting goes through its stage.
    connectable: false,
    deletable: false,
  }));
  // Pills only show where a call starts and ends: nothing can be done with them.
  const pills: CanvasFlowNode[] = terminalPills(agent, measured, view).map(({ id, kind, x, y }) => ({
    id,
    type: "terminal",
    position: { x, y },
    data: { kind },
    measured: measured[id],
    selectable: false,
    draggable: false,
    deletable: false,
    connectable: false,
    focusable: false,
  }));
  return [...nodes, ...cards, ...pills];
}

export function toFlowEdges(
  agent: Agent,
  selection: Selection,
  status: Map<string, StatusBadge[]> = new Map(),
  activeEdge: string | null = null,
  measured: Record<string, Dimensions> = {},
  view: CanvasView = canvasView(agent, [], measured),
): CanvasFlowEdge[] {
  // Edges to a missing node cannot be drawn; validation reports them on their node.
  const drawn = drawnEdges(agent, view);
  const end = view.endOf;

  // Back edges route around the cards and the pills.
  const pills = terminalPills(agent, measured, view);
  const boxes = new Map<string, Box>([...shownBoxes(agent, measured, view), ...pills.map((p) => [p.id, p] as const)]);
  const routes = routeBackEdges(
    boxes,
    drawn.map(({ source, edge }) => ({
      id: edgeId(source, edge.function),
      source: end(source),
      target: end(edge.target),
      label: edgeLabel(edge),
    })),
  );

  const pairCount = new Map<string, number>();
  for (const { source, edge } of drawn) {
    const pair = `${end(source)}->${end(edge.target)}`;
    pairCount.set(pair, (pairCount.get(pair) ?? 0) + 1);
  }
  const pairIndex = new Map<string, number>();

  const functionEdges = drawn.map(({ source, edge }): AgentFlowEdge => {
    const pair = `${end(source)}->${end(edge.target)}`;
    const index = pairIndex.get(pair) ?? 0;
    pairIndex.set(pair, index + 1);
    const selected = selection?.kind === "edge" && selection.source === source && selection.function === edge.function;
    const id = edgeId(source, edge.function);
    const active = id === activeEdge;
    return {
      id,
      type: "function",
      source: end(source),
      target: end(edge.target),
      data: {
        function: edge.function,
        label: edgeLabel(edge),
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
      markerEnd: {
        type: MarkerType.Arrow,
        color: active ? ACTIVE_STROKE : selected ? SELECTED_STROKE : EDGE_STROKE,
      },
    };
  });
  // Plain and unlabelled: React Flow's own curve, straight when the pill is centred on its card.
  const pillEdges = pills.map(
    ({ id, edgeId, kind, at }): TerminalFlowEdge => ({
      id: edgeId,
      type: "default",
      source: kind === "start" ? id : at,
      target: kind === "start" ? at : id,
      selectable: false,
      deletable: false,
      focusable: false,
      reconnectable: false,
      markerEnd: { type: MarkerType.Arrow, color: EDGE_STROKE },
    }),
  );
  return [...functionEdges, ...pillEdges];
}

/** A node's card where it is shown, with its measured size or the size it is laid out with. */
function cardBox(node: Node, measured: Record<string, Dimensions>, view: CanvasView): Box {
  return {
    ...view.shown(node),
    width: measured[node.name]?.width ?? NODE_WIDTH,
    height: measured[node.name]?.height ?? cardHeight(node),
  };
}

/** Every card shown, by id: the nodes not in a collapsed stage, and the collapsed stages' cards. */
function shownBoxes(agent: Agent, measured: Record<string, Dimensions>, view: CanvasView): Map<string, Box> {
  const cardSize = (id: string) => measured[id] ?? { width: NODE_WIDTH, height: NODE_HEIGHT };
  return new Map<string, Box>([
    ...agent.nodes.filter((n) => !view.hiddenIn.has(n.name)).map((n) => [n.name, cardBox(n, measured, view)] as const),
    ...[...view.cards.values()].map((card) => [card.id, { ...card.position, ...cardSize(card.id) }] as const),
  ]);
}

export type TerminalPill = Terminal & Box;

/**
 * The Start and End pills where they are shown: the Start pill above its card and
 * End pills below. A pill is centred on its card, except when an edge from above
 * also joins the card at the top (for Start), or one leaves it downwards (for
 * End): that edge runs where the pill would be, and its label sits halfway to the
 * other card. The pill then moves to the card's left or right edge, away from the
 * other cards, which clears even the widest label; with the other card straight
 * above or below, to the left, since back edges come in from the right. A card in
 * a stage frame keeps its pill inside the frame only where there is room;
 * otherwise the pill goes outside the frame, so it never lands in the frame's header.
 */
export function terminalPills(
  agent: Agent,
  measured: Record<string, Dimensions> = {},
  view: CanvasView = canvasView(agent, [], measured),
): TerminalPill[] {
  const boxes = shownBoxes(agent, measured, view);
  const byName = new Map(agent.nodes.map((n) => [n.name, n]));
  const frames = new Map(stageFrames(agent, measured, view).map((f) => [f.name, f]));
  // Edges between two cards, one below the other. Back edges and self-loops join
  // a card from the side (edgePath.ts), clear of a centred pill.
  const downward = drawnEdges(agent, view)
    .map(({ source, edge }) => ({ from: view.endOf(source), to: view.endOf(edge.target) }))
    .filter(({ from, to }) => boxes.get(to)!.y >= boxes.get(from)!.y + boxes.get(from)!.height);
  const centre = (box: Box) => box.x + box.width / 2;
  return [...view.terminals.values()].map((terminal) => {
    const card = boxes.get(terminal.at)!;
    // A collapsed stage's card is in no frame; a node shown is in its expanded stage's.
    const node = byName.get(terminal.at);
    const stage = node && stageOf(node);
    const frame = stage ? frames.get(stage) : undefined;
    const start = terminal.kind === "start";
    let y: number;
    if (start) {
      y = card.y - TERMINAL_GAP - TERMINAL_HEIGHT;
      if (frame && y < frame.y + FRAME_LABEL) y = frame.y - TERMINAL_GAP - TERMINAL_HEIGHT;
    } else {
      y = card.y + card.height + TERMINAL_GAP;
      if (frame && y + TERMINAL_HEIGHT > frame.y + frame.height - FRAME_PAD) y = frame.y + frame.height + TERMINAL_GAP;
    }
    // The cards at the other end of the downward edges on the pill's side of its card.
    const others = downward
      .filter(({ from, to }) => (start ? to : from) === terminal.at)
      .map(({ from, to }) => boxes.get(start ? from : to)!);
    const lean = others.reduce((sum, box) => sum + centre(box) - centre(card), 0);
    const x = (others.length === 0 ? centre(card) : lean < 0 ? card.x + card.width : card.x) - TERMINAL_WIDTH / 2;
    return { ...terminal, x, y, width: TERMINAL_WIDTH, height: TERMINAL_HEIGHT };
  });
}

// Room around a stage's cards inside its frame (#50), and above them for the label.
export const FRAME_PAD = 20;
export const FRAME_LABEL = 40;

export type StageFrame = Stage & Box;

/** The frame around each expanded stage's cards, where they are shown, in stage order. */
export function stageFrames(
  agent: Agent,
  measured: Record<string, Dimensions> = {},
  view: CanvasView = canvasView(agent, [], measured),
): StageFrame[] {
  const byName = new Map(agent.nodes.map((n) => [n.name, n]));
  return stagesOf(agent)
    .filter((stage) => !view.cards.has(stage.name))
    .map((stage) => {
      const cards = stage.nodes.map((name) => cardBox(byName.get(name)!, measured, view));
      const left = Math.min(...cards.map((c) => c.x)) - FRAME_PAD;
      const top = Math.min(...cards.map((c) => c.y)) - FRAME_LABEL;
      const right = Math.max(...cards.map((c) => c.x + c.width)) + FRAME_PAD;
      const bottom = Math.max(...cards.map((c) => c.y + c.height)) + FRAME_PAD;
      return { ...stage, x: left, y: top, width: right - left, height: bottom - top };
    });
}
