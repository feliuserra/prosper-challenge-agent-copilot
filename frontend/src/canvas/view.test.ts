import { describe, expect, it } from "vitest";

import { NODE_HEIGHT } from "../agent/layout";
import type { Agent } from "../agent/schema";
import { canvasView } from "./view";

const edge = (target: string) => ({ function: `to_${target}`, description: "", target });

// a, then stage S (b, c, d), then e, in a column 218 apart (98px cards, 120px gaps);
// `side` sits beside c, outside the stage.
const agent: Agent = {
  name: "v",
  initial_node: "a",
  nodes: [
    { name: "a", ui: { x: 0, y: 0 }, edges: [edge("b")] },
    { name: "b", stage: "S", ui: { x: 0, y: 218 }, edges: [edge("c")] },
    { name: "c", stage: "S", ui: { x: 0, y: 436 }, edges: [edge("d")] },
    { name: "d", stage: "S", ui: { x: 0, y: 654 }, edges: [edge("e")] },
    { name: "e", ui: { x: 0, y: 872 } },
  ],
};
const at = (name: string) => agent.nodes.find((n) => n.name === name)!;

describe("canvasView", () => {
  it("shows everything where it is stored when nothing is collapsed", () => {
    const view = canvasView(agent, []);
    expect(view.cards.size).toBe(0);
    expect(view.shown(at("e"))).toEqual({ x: 0, y: 872 });
    expect(view.endOf("c")).toBe("c");
    expect(view.stored({ x: 3, y: 500 })).toEqual({ x: 3, y: 500 });
  });

  it("hides a collapsed stage's nodes behind one card at its first node", () => {
    const view = canvasView(agent, ["S"]);
    expect([...view.hiddenIn]).toEqual([
      ["b", "S"],
      ["c", "S"],
      ["d", "S"],
    ]);
    const card = view.cards.get("S")!;
    expect(card.position).toEqual({ x: 0, y: 218 });
    expect(card.stage.nodes).toEqual(["b", "c", "d"]);
    expect(view.cardStage.get(card.id)).toBe("S");
    expect(view.endOf("c")).toBe(card.id);
    expect(view.endOf("a")).toBe("a");
  });

  it("moves what is below up by the height the stage frees, keeping the gap after it", () => {
    const view = canvasView(agent, ["S"]);
    const freed = 654 + NODE_HEIGHT - (218 + NODE_HEIGHT);
    expect(view.shown(at("e"))).toEqual({ x: 0, y: 872 - freed });
    // The gap between the card and e is the gap between d and e.
    expect(view.shown(at("e")).y - (218 + NODE_HEIGHT)).toBe(872 - (654 + NODE_HEIGHT));
    expect(view.shown(at("a"))).toEqual({ x: 0, y: 0 });
  });

  it("stores a position dragged below a collapsed stage where it would be with the stage expanded", () => {
    const view = canvasView(agent, ["S"]);
    for (const y of [0, 100, 218, 500, 900]) {
      const stored = view.stored({ x: 7, y });
      expect(stored.x).toBe(7);
      // What is stored is shown where it was dropped.
      expect(view.shown({ name: "x", ui: stored }).y).toBe(y);
    }
    expect(view.stored(view.shown(at("e")))).toEqual(at("e").ui);
  });

  it("keeps the space a node beside the stage needs", () => {
    const withSide: Agent = { ...agent, nodes: [...agent.nodes, { name: "side", ui: { x: 500, y: 436 } }] };
    const view = canvasView(withSide, ["S"]);
    const side = view.shown(withSide.nodes.at(-1)!);
    expect(side).toEqual({ x: 500, y: 436 - (436 - (218 + NODE_HEIGHT)) });
    // e moves up less than without `side`, and stays below it with its gap.
    expect(view.shown(at("e")).y).toBe(side.y + NODE_HEIGHT + (872 - (654 + NODE_HEIGHT)));
  });

  it("gives a card an id no node has, and ignores stages that do not exist", () => {
    const clash: Agent = { ...agent, nodes: [...agent.nodes, { name: "stage::S", ui: { x: 900, y: 0 } }] };
    const view = canvasView(clash, ["S", "Gone"]);
    expect(view.cards.get("S")!.id).not.toBe("stage::S");
    expect(view.cards.size).toBe(1);
  });
});
