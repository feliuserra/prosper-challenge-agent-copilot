import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";

import {
  autoLayout,
  cardHeight,
  NODE_HEIGHT,
  NODE_WIDTH,
  TERMINAL_GAP,
  TERMINAL_HEIGHT,
  TERMINAL_WIDTH,
} from "../agent/layout";
import type { Agent } from "../agent/schema";
import type { Problem } from "../validation/problems";
import {
  edgeId,
  FRAME_LABEL,
  FRAME_PAD,
  parseEdgeId,
  stageFrames,
  statusBadges,
  terminalPills,
  toFlowEdges,
  toFlowNodes,
  type AgentFlowEdge,
  type AgentFlowNode,
  type StageFlowNode,
  type TerminalFlowEdge,
  type TerminalFlowNode,
} from "./derive";
import { canvasView } from "./view";

/** The node cards among derived nodes (no stage is collapsed in these tests unless said). */
const nodeCards = (nodes: ReturnType<typeof toFlowNodes>) =>
  nodes.filter((n): n is AgentFlowNode => n.type === "agent");
/** The Start and End pills among derived nodes. */
const pillNodes = (nodes: ReturnType<typeof toFlowNodes>) =>
  nodes.filter((n): n is TerminalFlowNode => n.type === "terminal");
/** The agent's edges among derived edges, without the pills' plain edges. */
const functionEdges = (edges: ReturnType<typeof toFlowEdges>) =>
  edges.filter((e): e is AgentFlowEdge => e.type === "function");
const pillEdges = (edges: ReturnType<typeof toFlowEdges>) =>
  edges.filter((e): e is TerminalFlowEdge => e.type === "default");

const agent: Agent = {
  name: "a",
  initial_node: "start",
  nodes: [
    {
      name: "start",
      ui: { x: 10, y: 20 },
      edges: [
        { function: "book", description: "Call when the caller picks a time.", target: "next" },
        { function: "cancel", description: "", target: "next" },
        { function: "lost", description: "", target: "nowhere" },
      ],
    },
    { name: "next", ui: { x: 0, y: 200 }, end: true },
  ],
};

describe("toFlowNodes", () => {
  it("uses the name as id and the stored position, and marks the selection", () => {
    const nodes = nodeCards(toFlowNodes(agent, { kind: "node", name: "next" }, { next: { width: 240, height: 60 } }));
    expect(nodes.map((n) => [n.id, n.position, n.selected])).toEqual([
      ["start", { x: 10, y: 20 }, false],
      ["next", { x: 0, y: 200 }, true],
    ]);
    expect(nodes[1].measured).toEqual({ width: 240, height: 60 });
    expect(nodes[1].data.node).toBe(agent.nodes[1]);
  });
});

describe("toFlowEdges", () => {
  const edges = functionEdges(toFlowEdges(agent, { kind: "edge", source: "start", function: "cancel" }));

  it("uses `${source}::${function}` ids and skips edges to missing nodes", () => {
    expect(edges.map((e) => e.id)).toEqual(["start::book", "start::cancel"]);
    expect(edges.map((e) => e.selected)).toEqual([false, true]);
    // Only the selected edge can be reconnected.
    expect(edges.map((e) => e.reconnectable)).toEqual([false, "target"]);
  });

  it("labels an edge with its description, or its function name when it has none", () => {
    expect(edges.map((e) => e.data!.label)).toEqual(["When the caller picks a time.", "cancel"]);
  });

  it("draws an open arrowhead, coloured like the edge when selected or taken by a test call", () => {
    const colours = (flow: typeof edges) => flow.map((e) => (e.markerEnd as { color: string }).color);
    expect(edges.every((e) => (e.markerEnd as { type: string }).type === "arrow")).toBe(true);
    expect(colours(edges)).toEqual(["#b6bcc4", "#0969da"]);
    expect(colours(functionEdges(toFlowEdges(agent, null, new Map(), "start::book")))).toEqual(["#1a7f37", "#b6bcc4"]);
  });

  it("gives edges between the same two nodes their own lanes, a lone edge lane 0", () => {
    expect(edges.map((e) => e.data!.lane)).toEqual([-0.5, 0.5]);
    const loop: Agent = {
      name: "l",
      initial_node: "a",
      nodes: [{ name: "a", edges: [{ function: "again", description: "", target: "a" }] }],
    };
    expect(toFlowEdges(loop, null)[0].data!.lane).toBe(0);
  });
});

describe("statusBadges", () => {
  const problem = (node: string | null, edge: string | null, message: string, severity: Problem["severity"] = "error") => ({
    severity,
    message,
    node,
    edge,
  });

  it("puts node problems on the node and edge problems on the edge, matched by name", () => {
    const { nodes, edges } = statusBadges(agent, [
      problem("next", null, "Each task message needs a role."),
      problem("start", "book", "Property 'date' needs a type."),
    ]);
    expect([...nodes.keys()]).toEqual(["next"]);
    expect([...edges.keys()]).toEqual(["start::book"]);
    expect(edges.get("start::book")).toEqual([
      { tone: "error", label: "1 error", title: "Property 'date' needs a type." },
    ]);
  });

  it("shows several problems as one badge per severity, errors first", () => {
    const { nodes } = statusBadges(agent, [
      problem("start", null, "w", "warning"),
      problem("start", null, "a"),
      problem("start", null, "b"),
    ]);
    expect(nodes.get("start")).toEqual([
      { tone: "error", label: "2 errors", title: "a\nb" },
      { tone: "warning", label: "1 warning", title: "w" },
    ]);
  });

  it("puts a problem of an edge that is not drawn on its node, naming the edge", () => {
    const { nodes, edges } = statusBadges(agent, [problem("start", "lost", "Edge targets unknown node 'nowhere'.")]);
    expect(edges.size).toBe(0);
    expect(nodes.get("start")![0].title).toBe("lost: Edge targets unknown node 'nowhere'.");
  });

  it("gives agent-level problems and unknown nodes no badge", () => {
    const { nodes, edges } = statusBadges(agent, [problem(null, null, "Agent needs a name."), problem("gone", null, "x")]);
    expect(nodes.size + edges.size).toBe(0);
  });

  it("hands the badges to the flow nodes and edges", () => {
    const badges = statusBadges(agent, [problem("next", null, "n"), problem("start", "cancel", "e")]);
    const flowNodes = nodeCards(toFlowNodes(agent, null, {}, badges.nodes));
    const flowEdges = functionEdges(toFlowEdges(agent, null, badges.edges));
    expect(flowNodes.map((n) => n.data.status?.[0].title)).toEqual([undefined, "n"]);
    expect(flowEdges.map((e) => e.data!.status?.[0].title)).toEqual([undefined, "e"]);
  });
});

describe("a test call's position", () => {
  it("marks the active node and animates the edge taken", () => {
    const nodes = nodeCards(toFlowNodes(agent, null, {}, new Map(), "next"));
    expect(nodes.map((n) => n.data.active)).toEqual([false, true]);
    const edges = functionEdges(toFlowEdges(agent, null, new Map(), edgeId("start", "cancel")));
    expect(edges.map((e) => [e.animated, e.data!.active])).toEqual([
      [false, false],
      [true, true],
    ]);
  });

  it("marks nothing outside a call or for a node that is gone", () => {
    expect(nodeCards(toFlowNodes(agent, null)).some((n) => n.data.active)).toBe(false);
    expect(nodeCards(toFlowNodes(agent, null, {}, new Map(), "renamed")).some((n) => n.data.active)).toBe(false);
    expect(toFlowEdges(agent, null).some((e) => e.animated)).toBe(false);
  });
});

describe("edge ids", () => {
  it("round-trip, even when the node name contains '::'", () => {
    expect(parseEdgeId(edgeId("a::b", "go_to_c"))).toEqual({ source: "a::b", function: "go_to_c" });
  });
});

describe("stageFrames", () => {
  it("frames a stage's cards with padding and room for the label, using measured sizes", () => {
    const staged: Agent = {
      name: "f",
      initial_node: "a",
      nodes: [
        { name: "a", stage: "S", ui: { x: 0, y: 0 } },
        { name: "b", stage: "S", tools: ["find_slots"], ui: { x: 100, y: 300 } },
        { name: "c", ui: { x: 900, y: 900 } },
      ],
    };
    const [frame, ...rest] = stageFrames(staged, { a: { width: 400, height: 50 } });
    expect(rest).toEqual([]);
    expect(frame).toMatchObject({ name: "S", nodes: ["a", "b"], tone: 0 });
    expect(frame).toMatchObject({
      x: -FRAME_PAD,
      y: -FRAME_LABEL,
      width: 100 + NODE_WIDTH + 2 * FRAME_PAD,
      height: 300 + cardHeight(staged.nodes[1]) + FRAME_LABEL + FRAME_PAD,
    });
  });

  it("after autoLayout of the template, do not overlap, and each card is inside its own frame only", () => {
    const template = JSON.parse(
      readFileSync(new URL("../../../backend/agents/prosper-scheduler.json", import.meta.url), "utf8"),
    ) as Agent;
    // A branch out of the last stage, so stages also sit side by side.
    const branched: Agent = {
      ...template,
      nodes: [
        ...template.nodes.map((n) =>
          n.name === "offer_times"
            ? { ...n, edges: [...(n.edges ?? []), { function: "no_slot", description: "", target: "waitlist" }] }
            : n,
        ),
        { name: "waitlist", stage: "Waitlist" },
      ],
    };
    const laidOut = autoLayout(branched);
    const frames = stageFrames(laidOut);
    expect(frames.map((f) => f.name)).toEqual(["Identify caller", "Visit", "Change appointment", "Book", "Waitlist"]);
    type Rect = { x: number; y: number; width: number; height: number };
    const overlaps = (a: Rect, b: Rect) =>
      a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
    for (const [i, a] of frames.entries()) for (const b of frames.slice(i + 1)) expect(overlaps(a, b)).toBe(false);
    for (const n of laidOut.nodes) {
      const card = { x: n.ui!.x, y: n.ui!.y, width: NODE_WIDTH, height: cardHeight(n) };
      expect(frames.filter((f) => overlaps(f, card)).map((f) => f.name)).toEqual([n.stage]);
    }
  });
});

describe("a collapsed stage", () => {
  const to = (target: string) => ({ function: `to_${target}`, description: "", target });
  // a -> b -> c -> d, with b and c in stage S.
  const staged: Agent = {
    name: "c",
    initial_node: "a",
    nodes: [
      { name: "a", ui: { x: 0, y: 0 }, edges: [to("b")] },
      { name: "b", stage: "S", ui: { x: 0, y: 218 }, edges: [to("c")] },
      { name: "c", stage: "S", ui: { x: 0, y: 436 }, edges: [to("d")], end: true },
      { name: "d", ui: { x: 0, y: 654 } },
    ],
  };
  const view = canvasView(staged, ["S"]);
  const card = view.cards.get("S")!.id;
  const problems: Problem[] = [
    { severity: "error", message: "No task.", node: "c", edge: null },
    { severity: "warning", message: "No description.", node: "b", edge: "to_c" },
    { severity: "warning", message: "Leaves.", node: "c", edge: "to_d" },
  ];

  it("is one card with its steps and its nodes' badges, in place of its nodes", () => {
    const badges = statusBadges(staged, problems, view);
    const nodes = toFlowNodes(staged, null, {}, badges.nodes, "c", view);
    expect(nodes.filter((n) => n.type !== "terminal").map((n) => n.id)).toEqual(["a", "d", card]);
    const stageCard = nodes[2] as StageFlowNode;
    expect(stageCard.data.activeStep).toBe("c");
    expect(stageCard.data.stage.nodes).toEqual(["b", "c"]);
    expect(stageCard.data.status?.map((b) => [b.label, b.title])).toEqual([
      ["1 error", "c: No task."],
      ["1 warning", "b › to_c: No description."],
    ]);
    // An edge leaving the stage is drawn, with its own badge.
    expect(badges.edges.get(edgeId("c", "to_d"))?.[0].title).toBe("Leaves.");
  });

  it("hides the edges inside it, and ends the others at its card", () => {
    const edges = functionEdges(
      toFlowEdges(staged, { kind: "edge", source: "c", function: "to_d" }, new Map(), null, {}, view),
    );
    expect(edges.map((e) => [e.id, e.source, e.target, e.selected])).toEqual([
      ["a::to_b", "a", card, false],
      ["c::to_d", card, "d", true],
    ]);
  });

  it("has no frame", () => {
    expect(stageFrames(staged, {}, view)).toEqual([]);
    expect(stageFrames(staged).map((f) => f.name)).toEqual(["S"]);
  });
});

describe("Start and End pills", () => {
  const to = (target: string) => ({ function: `to_${target}`, description: "", target });
  // a -> b, a -> c; b and c both end the call.
  const branching: Agent = {
    name: "p",
    initial_node: "a",
    nodes: [
      { name: "a", ui: { x: 200, y: 0 }, edges: [to("b"), to("c")] },
      { name: "b", ui: { x: 0, y: 300 }, end: true },
      { name: "c", ui: { x: 500, y: 300 }, tools: ["find_slots"], end: true },
    ],
  };
  const centre = (x: number) => x + NODE_WIDTH / 2 - TERMINAL_WIDTH / 2;

  it("put Start above the start node and an End below every end node, centred on their cards", () => {
    const pills = pillNodes(toFlowNodes(branching, null));
    expect(pills.map((p) => [p.data.kind, p.position])).toEqual([
      ["start", { x: centre(200), y: -TERMINAL_GAP - TERMINAL_HEIGHT }],
      ["end", { x: centre(0), y: 300 + cardHeight(branching.nodes[1]) + TERMINAL_GAP }],
      ["end", { x: centre(500), y: 300 + cardHeight(branching.nodes[2]) + TERMINAL_GAP }],
    ]);
    // Nothing can be done with them.
    for (const pill of pills) {
      expect(pill).toMatchObject({ selectable: false, draggable: false, deletable: false, connectable: false });
    }
  });

  it("are joined to their cards by plain edges that cannot be selected, deleted or reconnected", () => {
    const [start, endB, endC] = pillNodes(toFlowNodes(branching, null)).map((p) => p.id);
    const edges = pillEdges(toFlowEdges(branching, null));
    expect(edges.map((e) => [e.source, e.target])).toEqual([
      [start, "a"],
      ["b", endB],
      ["c", endC],
    ]);
    for (const edge of edges) {
      expect(edge.data).toBeUndefined();
      expect(edge).toMatchObject({ selectable: false, deletable: false, reconnectable: false });
    }
    // The agent's own edges are unchanged.
    expect(functionEdges(toFlowEdges(branching, null)).map((e) => e.id)).toEqual(["a::to_b", "a::to_c"]);
  });

  it("follow a moved node, and the Start pill follows the start node", () => {
    const moved: Agent = {
      ...branching,
      nodes: branching.nodes.map((n) => (n.name === "b" ? { ...n, ui: { x: -100, y: 450 } } : n)),
    };
    const endB = pillNodes(toFlowNodes(moved, null))[1];
    expect(endB.position).toEqual({ x: centre(-100), y: 450 + NODE_HEIGHT + TERMINAL_GAP });

    const before = pillNodes(toFlowNodes(branching, null))[0];
    const after = pillNodes(toFlowNodes({ ...branching, initial_node: "c" }, null))[0];
    // Same pill, so React Flow moves it rather than drawing a new one. a -> c comes
    // in from the upper left: the pill sits at c's right edge, clear of it.
    expect(after.id).toBe(before.id);
    expect(after.position).toEqual({
      x: 500 + NODE_WIDTH - TERMINAL_WIDTH / 2,
      y: 300 - TERMINAL_GAP - TERMINAL_HEIGHT,
    });
  });

  it("move left of an edge from above into the start node, or down out of an end node, but not of back edges", () => {
    // a -> b -> c, all in a column; c goes back to a, and b ends the call although it has an edge.
    const column: Agent = {
      name: "k",
      initial_node: "b",
      nodes: [
        { name: "a", ui: { x: 0, y: 0 }, edges: [to("b")] },
        { name: "b", ui: { x: 0, y: 300 }, edges: [to("c")], end: true },
        { name: "c", ui: { x: 0, y: 600 }, edges: [to("a")] },
      ],
    };
    expect(terminalPills(column).map((p) => [p.kind, p.x])).toEqual([
      ["start", -TERMINAL_WIDTH / 2],
      ["end", -TERMINAL_WIDTH / 2],
    ]);
    // The back edge c -> a ends at a's top from the side: a centred Start pill is clear of it.
    expect(terminalPills({ ...column, initial_node: "a" })[0].x).toBe(centre(0));
    // With a coming in from the left, b's Start pill goes to the right.
    const fromLeft: Agent = {
      ...column,
      nodes: column.nodes.map((n) => (n.name === "a" ? { ...n, ui: { x: -300, y: 0 } } : n)),
    };
    expect(terminalPills(fromLeft)[0].x).toBe(NODE_WIDTH - TERMINAL_WIDTH / 2);
  });

  it("are not drawn for a start node that does not exist, or with no end node", () => {
    const pills = pillNodes(toFlowNodes({ ...branching, initial_node: "gone" }, null));
    expect(pills.map((p) => p.data.kind)).toEqual(["end", "end"]);
    const noEnd: Agent = { ...branching, nodes: branching.nodes.map(({ end: _end, ...n }) => n) };
    expect(pillNodes(toFlowNodes(noEnd, null)).map((p) => p.data.kind)).toEqual(["start"]);
  });

  it("sit outside a stage's frame, never in its header, unless there is room inside", () => {
    // Stage S: a above b; b ends the call and so does a node below it, c, in the same stage.
    const staged: Agent = {
      name: "s",
      initial_node: "a",
      nodes: [
        { name: "a", stage: "S", ui: { x: 0, y: 0 }, edges: [to("b")] },
        { name: "b", stage: "S", ui: { x: 0, y: 218 }, edges: [to("c")], end: true },
        { name: "c", stage: "S", ui: { x: 0, y: 436 }, end: true },
      ],
    };
    const [frame] = stageFrames(staged);
    const [start, endB, endC] = terminalPills(staged);
    expect(start.y + TERMINAL_HEIGHT + TERMINAL_GAP).toBe(frame.y);
    // b has a node below it in the frame: its End pill fits between them.
    expect(endB.y).toBe(218 + NODE_HEIGHT + TERMINAL_GAP);
    expect(endB.y + TERMINAL_HEIGHT).toBeLessThan(436);
    expect(endC.y).toBe(frame.y + frame.height + TERMINAL_GAP);
  });

  it("go on a collapsed stage's card, one End pill for all the end nodes in it", () => {
    const staged: Agent = {
      ...branching,
      nodes: branching.nodes.map((n) => ({ ...n, stage: n.name === "a" ? "First" : "Last" })),
    };
    const view = canvasView(staged, ["First", "Last"]);
    const [first, last] = [view.cards.get("First")!, view.cards.get("Last")!];
    const pills = pillNodes(toFlowNodes(staged, null, {}, new Map(), null, view));
    expect(pills.map((p) => p.data.kind)).toEqual(["start", "end"]);
    expect(pills[0].position).toEqual({ x: centre(200), y: first.position.y - TERMINAL_GAP - TERMINAL_HEIGHT });
    expect(pills[1].position.y).toBe(last.position.y + NODE_HEIGHT + TERMINAL_GAP);
    expect(pillEdges(toFlowEdges(staged, null, new Map(), null, {}, view)).map((e) => [e.source, e.target])).toEqual([
      [pills[0].id, first.id],
      [last.id, pills[1].id],
    ]);
  });

  it("move left on a collapsed stage's card that an edge leaves downwards", () => {
    // In stage S, a ends the call or goes on to b; S is collapsed and b is below it.
    const staged: Agent = {
      name: "x",
      initial_node: "a",
      nodes: [
        { name: "a", stage: "S", ui: { x: 0, y: 0 }, edges: [to("b")], end: true },
        { name: "b", ui: { x: 0, y: 300 } },
      ],
    };
    const view = canvasView(staged, ["S"]);
    const end = terminalPills(staged, {}, view).find((p) => p.kind === "end")!;
    expect(end.at).toBe(view.cards.get("S")!.id);
    expect(end.x).toBe(-TERMINAL_WIDTH / 2);
  });

  it("are obstacles for back edges", () => {
    // b -> a goes back up. e ends the call: its card is above the back edge's span,
    // but its End pill hangs down into it, left of the column the edge would take.
    const agentWith = (eEnds: boolean): Agent => ({
      name: "b",
      initial_node: "a",
      nodes: [
        { name: "a", ui: { x: 0, y: 0 }, edges: [to("b")] },
        { name: "b", ui: { x: 0, y: 300 }, edges: [to("a")] },
        { name: "e", ui: { x: 250, y: -100 }, end: eEnds },
      ],
    });
    const column = (a: Agent) => functionEdges(toFlowEdges(a, null)).find((e) => e.id === "b::to_a")!.data!.route!.x;
    const pill = terminalPills(agentWith(true)).find((p) => p.kind === "end")!;
    expect(pill.y).toBeGreaterThan(0);
    expect(column(agentWith(true))).toBeGreaterThan(pill.x + TERMINAL_WIDTH);
    expect(column(agentWith(true))).toBeGreaterThan(column(agentWith(false)));
  });

  it("have ids no node, card or edge has", () => {
    const clash: Agent = {
      name: "c",
      initial_node: "terminal::start",
      nodes: [
        { name: "terminal::start", ui: { x: 0, y: 0 }, edges: [{ function: "edge", description: "", target: "x" }] },
        { name: "x", ui: { x: 0, y: 300 }, end: true },
        { name: "terminal::end::x", ui: { x: 600, y: 0 } },
      ],
    };
    const nodes = toFlowNodes(clash, null);
    const edges = toFlowEdges(clash, null);
    expect(new Set(nodes.map((n) => n.id)).size).toBe(nodes.length);
    expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length);
    expect(pillNodes(nodes).map((p) => p.data.kind)).toEqual(["start", "end"]);
  });

  it("after autoLayout, overlap no card, no other pill and no frame but their own node's, and have no card next in line", () => {
    const template = JSON.parse(
      readFileSync(new URL("../../../backend/agents/prosper-scheduler.json", import.meta.url), "utf8"),
    ) as Agent;
    // An end node in the middle of the first stage too.
    const withTransfer: Agent = {
      ...template,
      nodes: [
        ...template.nodes.map((n) =>
          n.name === "greeting" ? { ...n, edges: [...(n.edges ?? []), to("transfer")] } : n,
        ),
        { name: "transfer", stage: "Identify caller", end: true },
      ],
    };
    // Without room for e's End pill, dagre puts c right below e, and the pill seems to lead into c.
    const diamond: Agent = {
      name: "d",
      initial_node: "a",
      nodes: [
        { name: "a", edges: [to("b"), to("e"), to("f")] },
        { name: "b", edges: [to("c")] },
        { name: "e", end: true },
        { name: "f", edges: [to("c")] },
        { name: "c", end: true },
      ],
    };
    type Rect = { x: number; y: number; width: number; height: number };
    const overlaps = (a: Rect, b: Rect) =>
      a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
    for (const agent of [template, withTransfer, diamond].map(autoLayout)) {
      const pills = terminalPills(agent);
      const frames = stageFrames(agent);
      const byName = new Map(agent.nodes.map((n) => [n.name, n]));
      const cards = agent.nodes.map((n) => ({ ...n.ui!, width: NODE_WIDTH, height: cardHeight(n) }));
      for (const [i, pill] of pills.entries()) {
        expect(cards.filter((card) => overlaps(pill, card))).toEqual([]);
        for (const other of pills.slice(i + 1)) expect(overlaps(pill, other)).toBe(false);
        const own = byName.get(pill.at)!.stage;
        expect(frames.filter((f) => f.name !== own && overlaps(f, pill))).toEqual([]);
        // A rank's distance on the open side of the pill: above Start, below End.
        const reach = 150;
        const open = { ...pill, y: pill.kind === "start" ? pill.y - reach : pill.y, height: pill.height + reach };
        expect(cards.filter((card) => overlaps(open, card))).toEqual([]);
      }
    }
    // The template's own pills are outside every frame: Start above the first stage, End below the last.
    const laidOut = autoLayout(template);
    const frames = stageFrames(laidOut);
    const [start, end] = terminalPills(laidOut);
    expect([start.at, end.at]).toEqual(["greeting", "confirm"]);
    expect(start.y + TERMINAL_HEIGHT).toBeLessThan(frames[0].y);
    expect(end.y).toBeGreaterThan(frames.at(-1)!.y + frames.at(-1)!.height);
  });
});
