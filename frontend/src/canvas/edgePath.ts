import { NODE_WIDTH } from "../agent/layout";

// Edge shapes. Edges always leave the bottom handle of a node and enter the top
// handle of their target (NodeCard), so only that case is handled here.
//
// Edges joining the same two nodes get lanes (-0.5 and 0.5 for two, -1, 0 and 1
// for three, ...): the curve bows sideways per lane, and labels stack vertically,
// so each label stays readable. Both ends stay on the handles, where the
// reconnect knob is.

const LANE_BOW = 40;
/** Vertical distance between stacked labels: a label's height plus a gap. */
export const LABEL_STACK = 26;
// How far a self-loop reaches past the right side of its node, and per lane.
const LOOP_OUT = 50;
const LOOP_LANE = 40;
const LOOP_REACH = 40;

export type EdgeGeometry = {
  path: string;
  labelX: number;
  labelY: number;
  /** "start": the label begins at labelX (beside a self-loop) instead of centring on it. */
  labelAlign: "center" | "start";
};

type Ends = { sourceX: number; sourceY: number; targetX: number; targetY: number; lane: number };

// React Flow's control-point rule (getBezierPath, curvature 0.25), so a lane-0
// edge is exactly the default bezier edge.
const controlOffset = (distance: number) => (distance >= 0 ? 0.5 * distance : 0.25 * 25 * Math.sqrt(-distance));

export function edgeGeometry({ sourceX, sourceY, targetX, targetY, lane }: Ends): EdgeGeometry {
  const offset = controlOffset(targetY - sourceY);
  const bow = lane * LANE_BOW;
  const [c1x, c1y] = [sourceX + bow, sourceY + offset];
  const [c2x, c2y] = [targetX + bow, targetY - offset];
  return {
    path: `M${sourceX},${sourceY} C${c1x},${c1y} ${c2x},${c2y} ${targetX},${targetY}`,
    // The curve at t = 0.5, computed as React Flow does.
    labelX: sourceX * 0.125 + c1x * 0.375 + c2x * 0.375 + targetX * 0.125,
    labelY: sourceY * 0.125 + c1y * 0.375 + c2y * 0.375 + targetY * 0.125 + lane * LABEL_STACK,
    labelAlign: "center",
  };
}

/** An edge from a node to itself: out of the bottom, round the right side, into the top. */
export function selfLoopGeometry({ sourceX, sourceY, targetX, targetY, lane }: Ends): EdgeGeometry {
  const right = sourceX + NODE_WIDTH / 2 + LOOP_OUT + lane * LOOP_LANE;
  const middle = (sourceY + targetY) / 2;
  return {
    path:
      `M${sourceX},${sourceY} C${sourceX},${sourceY + LOOP_REACH} ${right},${sourceY + LOOP_REACH} ${right},${middle} ` +
      `C${right},${targetY - LOOP_REACH} ${targetX},${targetY - LOOP_REACH} ${targetX},${targetY}`,
    labelX: right + 8,
    labelY: middle + lane * LABEL_STACK,
    labelAlign: "start",
  };
}

// Back edges: an edge into a node whose top is above the source's bottom (a
// retry or "go back"). A plain curve would run through the nodes in between, so
// it goes like a self-loop instead: out of the bottom, up a column right of
// every node it passes, into the top of the target.

/** A label's approximate width: 12px monospace text plus padding and border. */
const labelWidth = (text: string) => text.length * 7.3 + 14;

export type Box = { x: number; y: number; width: number; height: number };

/** Where a back edge runs: the x of its column, and its lane among back edges sharing it. */
export type BackRoute = { x: number; lane: number };

export type RoutedEdge = { id: string; source: string; target: string; label: string };

/**
 * Routes for the back edges among `edges` (the others are not in the result).
 * `boxes` are the node cards in flow coordinates. Columns clear every node the
 * edge passes and the self-loops beside them, labels included. Back edges that
 * would share a column and overlap vertically get separate lanes, shorter ones
 * inside, so nested loops do not cross.
 */
export function routeBackEdges(boxes: Map<string, Box>, edges: RoutedEdge[]): Map<string, BackRoute> {
  // How far right each node reaches, counting its self-loops and their labels.
  const loops = new Map<string, string[]>();
  for (const e of edges) if (e.source === e.target) loops.set(e.source, [...(loops.get(e.source) ?? []), e.label]);
  const reach = (name: string) => {
    const box = boxes.get(name)!;
    const labels = loops.get(name);
    if (!labels) return box.x + box.width;
    // The outermost loop (lanes are centred, as in toFlowEdges) and the widest label.
    const outer = LOOP_OUT + ((labels.length - 1) / 2) * LOOP_LANE;
    return box.x + box.width + outer + 8 + Math.max(...labels.map(labelWidth));
  };
  const byX = [...boxes].sort(([, a], [, b]) => a.x - b.x);

  const back = edges.flatMap((e) => {
    const s = boxes.get(e.source);
    const t = boxes.get(e.target);
    if (!s || !t || e.source === e.target || t.y >= s.y + s.height) return [];
    const top = t.y;
    const bottom = s.y + s.height;
    let column = Math.max(reach(e.source), reach(e.target)) + LOOP_OUT;
    // Left to right, so the column only moves right: any node in the span that
    // starts left of it pushes it past its right side.
    for (const [name, box] of byX) {
      if (box.y < bottom && box.y + box.height > top && box.x < column) {
        column = Math.max(column, reach(name) + LOOP_OUT);
      }
    }
    return [{ id: e.id, top, bottom, column }];
  });

  const routes = new Map<string, BackRoute>();
  const placed: { top: number; bottom: number; column: number; lane: number }[] = [];
  // Shorter spans first, so they take the inner lanes.
  for (const e of [...back].sort((a, b) => a.bottom - a.top - (b.bottom - b.top))) {
    const taken = new Set(
      placed.filter((p) => p.column === e.column && p.top < e.bottom && e.top < p.bottom).map((p) => p.lane),
    );
    let lane = 0;
    while (taken.has(lane)) lane++;
    placed.push({ ...e, lane });
    routes.set(e.id, { x: e.column + lane * LOOP_LANE, lane });
  }
  return routes;
}

/** A back edge along its column: out of the bottom of the source, into the top of the target. */
export function backEdgeGeometry({ sourceX, sourceY, targetX, targetY }: Omit<Ends, "lane">, route: BackRoute): EdgeGeometry {
  const x = route.x;
  return {
    path:
      `M${sourceX},${sourceY} C${sourceX},${sourceY + LOOP_REACH} ${x},${sourceY + LOOP_REACH} ${x},${sourceY} ` +
      `L${x},${targetY} C${x},${targetY - LOOP_REACH} ${targetX},${targetY - LOOP_REACH} ${targetX},${targetY}`,
    labelX: x + 8,
    labelY: (sourceY + targetY) / 2 + route.lane * LABEL_STACK,
    labelAlign: "start",
  };
}
