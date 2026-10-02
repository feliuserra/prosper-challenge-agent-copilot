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
