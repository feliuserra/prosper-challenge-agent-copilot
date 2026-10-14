import { cardHeight, NODE_HEIGHT } from "../agent/layout";
import type { Agent, Node, Position } from "../agent/schema";
import { stagesOf, type Stage } from "../agent/stages";

// What the canvas shows when stages are collapsed (#51). A collapsed stage is one
// card, the size of a node card, at its first node's position; its nodes are
// hidden. The vertical space the stage no longer needs is taken out of the canvas,
// so everything below it moves up. Positions in the agent never change: the shift
// applies to what is shown, and `stored` undoes it for a position the user drags.

export type Dimensions = { width: number; height: number };

/** A collapsed stage's card (a node card's size): its React Flow id, the stage, and where it is shown. */
export type StageCard = { id: string; stage: Stage; position: Position };

export type CanvasView = {
  /** Hidden node -> the collapsed stage it is in. */
  hiddenIn: Map<string, string>;
  /** Collapsed stage name -> its card. */
  cards: Map<string, StageCard>;
  /** Card id -> its stage's name. */
  cardStage: Map<string, string>;
  /** Where a visible node is shown. */
  shown(node: Node): Position;
  /** The position to store for one shown on the canvas. */
  stored(position: Position): Position;
  /** What an edge end is drawn at: the node itself, or the card of the collapsed stage it is in. */
  endOf(name: string): string;
};

type Span = [number, number];

/** `spans` merged into sorted, disjoint spans. */
function union(spans: Span[]): Span[] {
  const merged: Span[] = [];
  for (const [a, b] of [...spans].filter(([a, b]) => b > a).sort((p, q) => p[0] - q[0])) {
    const last = merged.at(-1);
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else merged.push([a, b]);
  }
  return merged;
}

/** The parts of the sorted disjoint `spans` not covered by any of `cover`. */
function subtract(spans: Span[], cover: Span[]): Span[] {
  let rest = spans;
  for (const [c, d] of cover) {
    rest = rest.flatMap(([a, b]): Span[] =>
      d <= a || c >= b ? [[a, b]] : ([[a, c], [d, b]] as Span[]).filter(([p, q]) => q > p),
    );
  }
  return rest;
}

export function canvasView(
  agent: Agent,
  collapsed: Iterable<string>,
  measured: Record<string, Dimensions> = {},
): CanvasView {
  const folded = new Set(collapsed);
  const byName = new Map(agent.nodes.map((n) => [n.name, n]));
  const top = (node: Node) => node.ui?.y ?? 0;
  const height = (node: Node) => measured[node.name]?.height ?? cardHeight(node);

  const hiddenIn = new Map<string, string>();
  const folds: { stage: Stage; id: string; first: Node; top: number; bottom: number }[] = [];
  const ids = new Set(byName.keys());
  for (const stage of stagesOf(agent)) {
    if (!folded.has(stage.name)) continue;
    const members = stage.nodes.map((name) => byName.get(name)!);
    for (const name of stage.nodes) hiddenIn.set(name, stage.name);
    // Node names can be any text: make sure no node, or other card, has the card's id.
    let id = `stage::${stage.name}`;
    while (ids.has(id)) id = `:${id}`;
    ids.add(id);
    folds.push({
      stage,
      id,
      first: members[0],
      top: Math.min(...members.map(top)),
      bottom: Math.max(...members.map((n) => top(n) + height(n))),
    });
  }

  // The space taken out: below each card, down to its stage's last node, except
  // where something still shown (a node beside the stage, another card) needs it.
  const removed = subtract(
    union(folds.map((f) => [f.top + NODE_HEIGHT, f.bottom])),
    union([
      ...agent.nodes.filter((n) => !hiddenIn.has(n.name)).map((n): Span => [top(n), top(n) + height(n)]),
      ...folds.map((f): Span => [f.top, f.top + NODE_HEIGHT]),
    ]),
  );
  /** How far up something stored at `y` is shown: the space taken out above it. */
  const shift = (y: number) => removed.reduce((sum, [a, b]) => sum + Math.max(0, Math.min(b, y) - a), 0);

  const cards = new Map<string, StageCard>(
    folds.map((f) => {
      const position = { x: f.first.ui?.x ?? 0, y: f.top - shift(f.top) };
      return [f.stage.name, { id: f.id, stage: f.stage, position }];
    }),
  );
  return {
    hiddenIn,
    cards,
    cardStage: new Map(folds.map((f) => [f.id, f.stage.name])),
    shown: (node) => ({ x: node.ui?.x ?? 0, y: top(node) - shift(top(node)) }),
    stored({ x, y }) {
      // Walk the removed spans from the top: each one starting above the stored
      // position found so far lies above it, so its height is added back.
      let back = 0;
      for (const [a, b] of removed) {
        if (y + back > a) back += b - a;
        else break;
      }
      return { x, y: y + back };
    },
    endOf: (name) => {
      const stage = hiddenIn.get(name);
      return stage === undefined ? name : cards.get(stage)!.id;
    },
  };
}

/** The view with nothing collapsed: everything shown where it is stored. */
export const flatView: CanvasView = {
  hiddenIn: new Map(),
  cards: new Map(),
  cardStage: new Map(),
  shown: (node) => ({ x: node.ui?.x ?? 0, y: node.ui?.y ?? 0 }),
  stored: (position) => position,
  endOf: (name) => name,
};
