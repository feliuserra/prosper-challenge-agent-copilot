import { describe, expect, it } from "vitest";

import type { Agent } from "../agent/schema";
import { stagesOf } from "../agent/stages";
import { arrowSize, toFlowEdges, toFlowNodes, type AgentFlowEdge, type AgentFlowNode, type StageFlowNode } from "../canvas/derive";
import { canvasView } from "../canvas/view";
import {
  canvasHeat,
  defaultOptions,
  EDGE_MAX,
  EDGE_MIN,
  edgeTraffic,
  hashFor,
  heatColor,
  heatLines,
  nodeHeats,
  optionsFor,
  optionsFromHash,
  pathText,
  stageHeat,
  type HeatOptions,
} from "./heat";
import type { BaselineNumbers, Detection, Issue, NodeNumbers, SignalNumbers } from "./types";

const edge = (fn: string, target: string) => ({ function: fn, description: "", target });

// greeting -> ask_name -> confirm_name (loops back) -> verify; `custom` is the open
// agent's own node, which no call went through. Stage "Identify": the first three.
const agent: Agent = {
  name: "t",
  initial_node: "greeting",
  nodes: [
    { name: "greeting", stage: "Identify", ui: { x: 0, y: 0 }, edges: [edge("choose_intent", "ask_name")] },
    { name: "ask_name", stage: "Identify", ui: { x: 0, y: 218 }, edges: [edge("record_spelling", "confirm_name")] },
    {
      name: "confirm_name",
      stage: "Identify",
      ui: { x: 0, y: 436 },
      edges: [edge("name_confirmed", "verify"), edge("correct_spelling", "confirm_name"), edge("spell_again", "ask_name")],
    },
    { name: "verify", ui: { x: 0, y: 654 }, edges: [edge("go_custom", "custom")] },
    { name: "custom", ui: { x: 0, y: 872 }, end: true },
  ],
};

const base = (k: number, n: number, p: number, flagged = false): BaselineNumbers => ({ k, n, rate: k / n, p, flagged });
const sig = (k: number, n: number, extra: Partial<SignalNumbers> = {}): SignalNumbers => ({ k, n, rate: k / n, ...extra });
const node = (entered: number, exits: Record<string, number>, signals: NodeNumbers["signals"]): NodeNumbers => ({
  entered,
  exits,
  signals,
});

function issue(over: Partial<Issue>): Issue {
  return {
    id: "a:confirm_name:stall",
    clinic: "a",
    node: "confirm_name",
    shape: "stall",
    severity: "low",
    version: 2,
    signal: "reentry",
    label: "re-entries",
    rate: 0.09,
    base_rate: 0.02,
    baseline: "fleet",
    extra_per_week: 600,
    score: 600,
    since_week: "2026-09-28",
    since_version: 2,
    trend: [],
    direction: "steady",
    evidence: [
      { signal: "reentry", label: "re-entries", baseline: "version", against: 1, rate: 0.09, base_rate: 0.02, k: 90, n: 1000, p: 1e-9, extra_per_week: 700 },
      { signal: "reentry", label: "re-entries", baseline: "fleet", against: "other clinics", rate: 0.09, base_rate: 0.024, k: 90, n: 1000, p: 1e-6, extra_per_week: 600 },
    ],
    examples: ["a-1"],
    ...over,
  };
}

const detection: Detection = {
  available: true,
  week: "2026-10-05",
  end: "2026-10-11T23:59:00",
  calls: 4000,
  clinics: [
    { id: "a", versions: [{ version: 1, from: "", to: "", calls: 2000 }, { version: 2, from: "", to: "", calls: 2000 }] },
    { id: "b", versions: [{ version: 1, from: "", to: "", calls: 500 }] },
  ],
  issues: [
    issue({}),
    issue({ id: "a:verify:error", node: "verify", shape: "error", signal: "tool_error", extra_per_week: 150, score: 300, evidence: [] }),
  ],
  example_calls: {},
  nodes: {
    a: {
      "1": { greeting: node(1000, { choose_intent: 950 }, { hang_up: sig(50, 1000) }) },
      "2": {
        greeting: node(1000, { choose_intent: 940 }, { hang_up: sig(60, 1000, { version: base(50, 1000, 0.2), fleet: base(25, 500, 0.01) }) }),
        ask_name: node(940, { record_spelling: 980 }, {
          reentry: sig(0, 940, { version: base(0, 950, 1) }),
          hang_up: sig(12, 940, { version: base(10, 950, 0.3) }),
        }),
        confirm_name: node(1000, { name_confirmed: 900, correct_spelling: 70, spell_again: 20 }, {
          // 9% against 2%: 7 points above, the hottest
          reentry: sig(90, 1000, { version: base(20, 1000, 1e-12, true), fleet: base(12, 500, 1e-4, true) }),
          // 3.5 points above, but it could be chance
          hang_up: sig(45, 1000, { version: base(10, 1000, 0.2) }),
        }),
        verify: node(900, { go_custom: 850 }, {
          reentry: sig(0, 900, { version: base(0, 900, 1) }),
          tool_error: sig(40, 900, { version: base(5, 900, 1e-6, true) }),
        }),
      },
    },
    b: { "1": { greeting: node(500, { choose_intent: 480 }, { hang_up: sig(25, 500) }) } },
  },
  settings: {
    window_weeks: 4,
    alpha: 0.05,
    allowance: { version: 1, fleet: 1.2 },
    min_relative: { version: 1.2, fleet: 1.5 },
    min_absolute: 0.002,
    min_events: 5,
    stall_turns: 6,
  },
  signals: {
    reentry: { label: "re-entries", shape: "stall" },
    stall: { label: "stalls", shape: "stall" },
    hang_up: { label: "hang-ups", shape: "leak" },
    transfer: { label: "transfers", shape: "detour" },
    error: { label: "errors", shape: "error" },
    tool_error: { label: "tool errors", shape: "error" },
    duplicate: { label: "duplicate patients", shape: "silent" },
    callback: { label: "callbacks within 48 h", shape: "silent" },
    quick_change: { label: "bookings changed within 24 h", shape: "silent" },
  },
};

const options: HeatOptions = { clinic: "a", version: "2", compare: "version", signal: "reentry" };

describe("node tints", () => {
  it("tints by how far the rate is above the baseline: the stall is the hottest node", () => {
    const heats = nodeHeats(detection, options, agent);
    const confirm = heats.get("confirm_name")!;
    expect(confirm.tint).toBe(1);
    expect(confirm.rate).toBeCloseTo(0.09);
    expect(confirm.base).toBeCloseTo(0.02);
    expect(confirm.flagged).toBe(true);
    const hottest = [...heats].sort((a, b) => b[1].tint - a[1].tint)[0][0];
    expect(hottest).toBe("confirm_name");
    expect(heats.get("ask_name")!.tint).toBe(0);
  });

  it("scales the tint up to TINT_FULL points above the baseline", () => {
    const heats = nodeHeats(detection, { ...options, signal: "tool_error" }, agent);
    // 4.4% against 0.6%: 3.9 points of 5.
    expect(heats.get("verify")!.tint).toBeCloseTo((40 / 900 - 5 / 900) / 0.05);
  });

  it("does not tint a rise that could be chance", () => {
    const heats = nodeHeats(detection, { ...options, signal: "hang_up" }, agent);
    expect(heats.get("confirm_name")!.rate).toBeCloseTo(0.045);
    expect(heats.get("confirm_name")!.tint).toBe(0);
    expect(heats.get("greeting")!.tint).toBe(0); // 6% against 5%, p 0.2
  });

  it("compares with the other clinics when asked", () => {
    const heats = nodeHeats(detection, { ...options, compare: "fleet", signal: "hang_up" }, agent);
    expect(heats.get("greeting")!.base).toBeCloseTo(0.05);
    expect(heats.get("greeting")!.tint).toBeCloseTo(0.01 / 0.05);
  });

  it("says why a node has no tint", () => {
    const heats = nodeHeats(detection, options, agent);
    expect(heats.get("custom")!.tint).toBe(0);
    expect(heats.get("custom")!.note).toMatch(/No calls went through a node called custom in a v2/);
    expect(heats.get("greeting")!.note).toMatch(/No re-entries are measured/);
    const fleet = nodeHeats(detection, { ...options, compare: "fleet" }, agent);
    expect(fleet.get("ask_name")!.note).toMatch(/No other clinic has a node called ask_name/);
    const first = nodeHeats(detection, { ...options, version: "1", signal: "hang_up" }, agent);
    expect(first.get("greeting")!.note).toMatch(/No earlier version/);
    expect(first.get("greeting")!.rate).toBeCloseTo(0.05);
  });

  it("in the issues view, tints by the extra calls a week of each node's issues", () => {
    const heats = nodeHeats(detection, { ...options, signal: "issues" }, agent);
    expect(heats.get("confirm_name")!.tint).toBe(1);
    expect(heats.get("verify")!.tint).toBeCloseTo(150 / 600);
    expect(heats.get("greeting")!.tint).toBe(0);
    expect(heats.get("confirm_name")!.issues.map((i) => i.id)).toEqual(["a:confirm_name:stall"]);
    // Issues are for the version running now.
    expect(nodeHeats(detection, { ...options, version: "1", signal: "issues" }, agent).get("confirm_name")!.issues).toEqual([]);
  });
});

describe("edge widths", () => {
  it("are traffic: the busiest edge is the widest", () => {
    const traffic = edgeTraffic(detection, options, agent);
    expect(traffic.get("ask_name::record_spelling")).toEqual({ calls: 980, width: EDGE_MAX });
    expect(traffic.get("confirm_name::correct_spelling")!.width).toBeCloseTo(EDGE_MIN + ((EDGE_MAX - EDGE_MIN) * 70) / 980);
    expect(traffic.get("verify::go_custom")!.calls).toBe(850);
  });

  it("are the thinnest where no call went", () => {
    const traffic = edgeTraffic(detection, { ...options, clinic: "b", version: "1" }, agent);
    expect(traffic.get("confirm_name::name_confirmed")).toEqual({ calls: 0, width: EDGE_MIN });
  });
});

describe("collapsed stages", () => {
  const identify = stagesOf(agent)[0];

  it("roll their nodes up, weighted by traffic", () => {
    const heats = nodeHeats(detection, options, agent);
    const stage = stageHeat(identify, heats, "reentry");
    // ask_name 0 of 940 and confirm_name 90 of 1000; greeting does not measure re-entries.
    expect(stage.rate).toBeCloseTo(90 / 1940);
    expect(stage.base).toBeCloseTo((0 * 940 + 0.02 * 1000) / 1940);
    expect(stage.tint).toBeCloseTo((90 / 1940 - 20 / 1940) / 0.05);
    expect(stage.entered).toBe(1000); // the busiest step: a call through all three counts once
    expect(stage.flagged).toBe(true);
    expect(stage.issues.map((i) => i.node)).toEqual(["confirm_name"]);
  });

  it("are not tinted when none of their nodes is", () => {
    const heats = nodeHeats(detection, { ...options, signal: "hang_up" }, agent);
    const stage = stageHeat(identify, heats, "hang_up");
    expect(stage.rate).toBeCloseTo((60 + 12 + 45) / (1000 + 940 + 1000));
    expect(stage.tint).toBe(0);
  });

  it("take the hottest node in the issues view", () => {
    const heats = nodeHeats(detection, { ...options, signal: "issues" }, agent);
    expect(stageHeat(identify, heats, "issues").tint).toBe(1);
  });

  it("get their heat and lines on the canvas, by card id", () => {
    const view = canvasView(agent, ["Identify"]);
    const heat = canvasHeat(detection, options, agent, view);
    const card = view.cards.get("Identify")!;
    expect(heat.nodes.get(card.id)!.lines).toEqual(["Re-entries: 4.6% across 3 steps", "1.0% in v1 · flagged"]);
    const nodes = toFlowNodes(agent, null, {}, new Map(), null, view, heat);
    const stageNode = nodes.find((n) => n.type === "stage") as StageFlowNode;
    expect(stageNode.data.heat!.rate).toBeCloseTo(90 / 1940);
  });
});

describe("the canvas", () => {
  const view = canvasView(agent, []);
  const heat = canvasHeat(detection, options, agent, view);

  it("puts each node's heat and lines on its card", () => {
    const nodes = toFlowNodes(agent, null, {}, new Map(), null, view, heat);
    const confirm = nodes.find((n) => n.id === "confirm_name") as AgentFlowNode;
    expect(confirm.data.heat!.tint).toBe(1);
    expect(confirm.data.heat!.lines).toEqual(["Re-entries: 9.0% of 1,000", "2.0% in v1 · flagged"]);
    const plain = toFlowNodes(agent, null, {}, new Map(), null, view) as AgentFlowNode[];
    expect(plain.every((n) => n.type !== "agent" || n.data.heat === undefined)).toBe(true);
  });

  it("widens edges by traffic and keeps their arrowheads in proportion", () => {
    const edges = toFlowEdges(agent, null, new Map(), null, {}, view, heat);
    const busiest = edges.find((e) => e.id === "ask_name::record_spelling") as AgentFlowEdge;
    expect(busiest.data!.traffic!.width).toBe(EDGE_MAX);
    expect(busiest.markerEnd).toMatchObject({ width: arrowSize(EDGE_MAX), height: arrowSize(EDGE_MAX) });
    expect(arrowSize(EDGE_MAX) * EDGE_MAX).toBe(3 * EDGE_MAX);
    const plain = toFlowEdges(agent, null, new Map(), null, {}, view)[0] as AgentFlowEdge;
    expect(plain.data!.traffic).toBeUndefined();
  });
});

describe("options", () => {
  it("open on the agent's clinic, the version it runs now and the issues", () => {
    expect(defaultOptions(detection, "a")).toEqual({ clinic: "a", version: "2", compare: "version", signal: "issues" });
    // A clinic with one version is compared with the other clinics.
    expect(defaultOptions(detection, "b")).toEqual({ clinic: "b", version: "1", compare: "fleet", signal: "issues" });
    // An agent whose clinic has no calls opens on the most urgent issue's clinic.
    expect(defaultOptions(detection, "riverside").clinic).toBe("a");
  });

  it("keep what was chosen where the data has it", () => {
    expect(defaultOptions(detection, null, { clinic: "a", version: "1", compare: "version", signal: "hang_up" })).toEqual({
      clinic: "a",
      version: "1",
      compare: "fleet", // v1 has no earlier version
      signal: "hang_up",
    });
    expect(defaultOptions(detection, null, { clinic: "zzz", version: "9" }).clinic).toBe("a");
  });

  it("show an issue against the version it started in when that flagged it", () => {
    expect(optionsFor(detection.issues[0])).toEqual({ clinic: "a", version: "2", compare: "version", signal: "reentry" });
    expect(optionsFor(detection.issues[1]).compare).toBe("fleet");
  });

  it("round-trip through a link", () => {
    expect(optionsFromHash(hashFor(options))).toEqual(options);
    expect(optionsFromHash("#calls")).toEqual({});
    expect(optionsFromHash("#other")).toBeNull();
    expect(optionsFromHash("#calls=linden-grove/2/sideways/hang_up")).toEqual({
      clinic: "linden-grove",
      version: "2",
      signal: "hang_up",
    });
  });
});

describe("words and colours", () => {
  it("cards say the rate and the baseline", () => {
    const heats = nodeHeats(detection, { ...options, compare: "fleet" }, agent);
    expect(heatLines(detection, heats.get("confirm_name")!, { ...options, compare: "fleet" })).toEqual([
      "Re-entries: 9.0% of 1,000",
      "2.4% in other clinics · flagged",
    ]);
    const issues = nodeHeats(detection, { ...options, signal: "issues" }, agent);
    expect(heatLines(detection, issues.get("confirm_name")!, { ...options, signal: "issues" })).toEqual([
      "1 issue: stall",
      "About 600 more calls a week",
    ]);
    expect(heatLines(detection, issues.get("greeting")!, { ...options, signal: "issues" })).toEqual([
      "No issues",
      "1,000 calls entered",
    ]);
  });

  it("paths read as steps, loops counted", () => {
    expect(pathText([["greeting", 1], ["confirm_name", 1, "x"], ["confirm_name", 2, "correct_spelling"], ["verify", 1, "y"]])).toBe(
      "Greeting › Confirm name ×2 › Verify",
    );
  });

  it("tints run from white to orange", () => {
    expect(heatColor(0)).toBe("rgb(255 255 255)");
    expect(heatColor(1)).toBe("rgb(244 140 70)");
    expect(heatColor(7)).toBe(heatColor(1));
  });
});
