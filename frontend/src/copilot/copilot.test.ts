import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "../agent/schema";
import { selectIsDirty, useAgentStore } from "../store/agentStore";
import { undo } from "../store/history";
import { parseEvents, type Proposal, type Spec, type StepEvent } from "./api";
import {
  accept,
  acceptRefusal,
  build,
  describe as line,
  fixIssue,
  fixRefusal,
  loadWorkspace,
  reject,
  selectCanUseRehearsal,
  stop,
  switchToRehearsal,
  useCopilotStore,
} from "./copilotStore";
import { questionsText } from "./CopilotPanel";
import { nodeDiff, positioned } from "./diff";

const exampleText = readFileSync(new URL("../../../backend/tests/fixtures/linear-agent.json", import.meta.url), "utf8");
const example = () => JSON.parse(exampleText) as Agent;

const editor = () => useAgentStore.getState();
const copilot = () => useCopilotStore.getState();

/** The example with one node's task changed and a node added after `confirm`. */
function proposed(): Agent {
  const agent = example();
  const nodes = agent.nodes.map((n) =>
    n.name === "greeting" ? { ...n, task_messages: [{ role: "developer" as const, content: "Greet warmly." }] } : n,
  );
  nodes.push({ name: "wrap_up", task_messages: [{ role: "developer", content: "Say goodbye." }], edges: [] });
  return { ...agent, nodes };
}

describe("parseEvents", () => {
  it("returns complete events and keeps a partial one for the next chunk", () => {
    const one = 'event: part\ndata: {"event": "part", "part": "build", "status": "running"}\n\n';
    const two = 'event: done\ndata: {"event": "done"}\n\n';
    const cut = one.length + 10;
    const first = parseEvents((one + two).slice(0, cut));
    expect(first.events.map((e) => e.event)).toEqual(["part"]);
    const second = parseEvents(first.rest + (one + two).slice(cut));
    expect(second.events.map((e) => e.event)).toEqual(["done"]);
    expect(second.rest).toBe("");
  });
});

describe("nodeDiff and positioned", () => {
  it("marks added and changed nodes and lists removed ones, ignoring positions and stages", () => {
    const draft = { ...example(), nodes: example().nodes.map((n) => ({ ...n, ui: { x: 1, y: 2 }, stage: "Somewhere" })) };
    const proposal = proposed();
    proposal.nodes = proposal.nodes.filter((n) => n.name !== "offer_times");
    const diff = nodeDiff(proposal, draft);
    expect(Object.fromEntries(diff.marks)).toEqual({ greeting: "changed", wrap_up: "added" });
    expect(diff.removed).toEqual(["offer_times"]);
  });

  it("keeps the draft's positions by name and places new nodes", () => {
    const draft = positioned(example(), null);
    const shown = positioned(proposed(), draft);
    const at = (agent: Agent, name: string) => agent.nodes.find((n) => n.name === name)!.ui;
    expect(at(shown, "greeting")).toEqual(at(draft, "greeting"));
    expect(at(shown, "wrap_up")).toBeDefined();
  });
});

describe("progress lines", () => {
  it("describes the build's events", () => {
    const op: StepEvent = { event: "operation", index: 1, operation: { op: "update_node", name: "greeting" }, agent: example() };
    expect(line(op)?.text).toBe("Operation 2: update node greeting");
    const round: StepEvent = { event: "round", round: 1, kept: false, reason: "None of the failing tests passed." };
    expect(line(round)?.text).toBe("Round 1: change not kept. None of the failing tests passed.");
  });

  it("describes a fix's events (#33)", () => {
    expect(line({ event: "backcast", k: 5, passed: 0, failed: 5, rate: "0/5" })?.text).toBe(
      "Reproduction on the current agent: 5 of 5 continuations fail",
    );
    const turn: StepEvent = { event: "candidate", number: 2, rationale: "Ask for the spelling.", turn: { passed: 4, rate: "4/5" } };
    expect(line(turn)?.text).toBe("Candidate 2: 4/5 at the decisive turn. Ask for the spelling.");
    const full: StepEvent = { event: "candidate", number: 2, full: { k: 5, passed: 3, failed: 2, rate: "3/5" } };
    expect(line(full)?.text).toBe("Candidate 2: 3/5 in full");
    expect(line({ event: "done", fix: { created: "", issue: fixed, outcome: "not_reproduced", message: "It did not come back." } })?.text).toBe(
      "It did not come back.",
    );
  });
});

const fixed = { call: "lg-1019-0804", turn: 4, kind: "wrong_patient", label: "wrong patient or name", requirement: "B3", summary: "", node: "ask_name" };

describe("a fix from an issue (#33)", () => {
  beforeEach(async () => {
    editor().open("demo", example());
    backend({ "GET /guidelines": json({ text: "" }), "GET /spec": json(emptySpec) });
    await loadWorkspace("demo");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("needs the issue's agent open and saved", () => {
    expect(fixRefusal("demo")).toBeNull();
    expect(fixRefusal("linden-grove")).toMatch(/Open the agent linden-grove first/);
    editor().updateAgent({ name: "Unsaved" });
    expect(fixRefusal("demo")).toMatch(/Save the draft first/);
  });

  it("streams the fix and shows its proposal on the canvas", async () => {
    const fix = { created: "", issue: fixed, outcome: "proposal", message: "Proposal 3 is ready.", proposal: 3 };
    const events = [
      { event: "part", part: "reproduction", status: "running" },
      { event: "backcast", k: 5, passed: 0, failed: 5, rate: "0/5" },
      { event: "candidate", number: 1, rationale: "Ask for the spelling.", turn: { passed: 5, rate: "5/5" } },
      { event: "done", fix, proposal: proposal({ kind: "fix", issue: fixed }) },
    ];
    const calls = backend({
      "POST /fix": streamed(sse(events)),
      "GET /spec": json(emptySpec),
      "GET /fixes/last": json(fix),
      "GET /proposals/last": json(proposal({ kind: "fix", issue: fixed })),
    });
    await fixIssue("lg-1019-0804", 4);
    expect(calls.find((c) => c.path === "/fix")?.body).toEqual({ call: "lg-1019-0804", turn: 4, cached: false });
    expect(copilot().canvas?.mode).toBe("proposal");
    expect(copilot().proposal?.kind).toBe("fix");
    expect(copilot().fix?.outcome).toBe("proposal");
    expect(copilot().step?.log.map((l) => l.text)).toEqual([
      "Reproduction: working…",
      "Reproduction on the current agent: 5 of 5 continuations fail",
      "Candidate 1: 5/5 at the decisive turn. Ask for the spelling.",
      "Proposal 3 is ready.",
    ]);
    expect(acceptRefusal()).toBeNull();
  });
});

describe("questions for the client", () => {
  it("lists each question with its default", () => {
    const spec = { questions: [{ id: "Q1", question: "Do you see walk-ins?", default: "No walk-ins." }] } as Spec;
    expect(questionsText(spec, null)).toBe(
      "Questions about your guidelines:\n\n1. Do you see walk-ins?\n   Until we hear from you: No walk-ins.\n",
    );
  });
});

// ---- building and deciding, against a fake backend ----------------------------------------------
const proposal = (overrides: Partial<Proposal> = {}): Proposal =>
  ({
    number: 3,
    created: "2026-10-16T10:00:00+00:00",
    status: "ready",
    blocked: [],
    started_from: { template: "prosper-scheduler", hash: "x", agent: null },
    configuration: null,
    configuration_entries: 0,
    configuration_changes: [],
    outline: [],
    operations: [{ op: "update_node" }],
    agent: proposed(),
    uncarried: [],
    diagnoses: [],
    questions: [],
    concerns: [],
    rounds: [],
    results: null,
    leaks: [],
    meta: { seconds: 1, cost: { copilot: 0, tests: 0 } },
    ...overrides,
  }) as Proposal;

const sse = (events: object[]) => events.map((e) => `event: x\ndata: ${JSON.stringify(e)}\n\n`).join("");

/** A fetch that answers by method and path; a stream answer is sent in two chunks. */
function backend(routes: Record<string, () => Response>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = url.replace("/copilot/workspaces/demo", "");
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null });
    const route = routes[`${method} ${path}`];
    return route ? route() : new Response(JSON.stringify({ detail: "Not found" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetch);
  return calls;
}

const json = (body: unknown) => () => new Response(JSON.stringify(body));

function streamed(text: string, hold?: Promise<void>): () => Response {
  return () =>
    new Response(
      new ReadableStream({
        async start(controller) {
          const half = Math.floor(text.length / 2);
          controller.enqueue(new TextEncoder().encode(text.slice(0, half)));
          await hold;
          controller.enqueue(new TextEncoder().encode(text.slice(half)));
          controller.close();
        },
      }),
    );
}

const emptySpec = { requirements: [], set_aside: [], questions: [], configuration: null, tests: [] };

describe("the rehearsal's result (#34)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("stops a slow step and replays the agent's recording instead", async () => {
    editor().open("demo", example());
    backend({ "GET /guidelines": json({ text: "" }), "GET /spec": json(emptySpec), "GET /recordings": json({ steps: ["build"] }) });
    await loadWorkspace("demo");
    expect(copilot().recordings).toEqual(["build"]);
    let release = () => {};
    const slow = new Promise<void>((resolve) => (release = resolve));
    const events = [
      { event: "part", part: "build", status: "running", agent: example() },
      { event: "done", proposal: proposal() },
    ];
    let builds = 0;
    const calls = backend({
      "POST /build": () => (builds++ === 0 ? streamed(sse(events), slow)() : streamed(sse(events))()),
      "GET /spec": json(emptySpec),
      "GET /proposals/last": json(proposal()),
    });
    const live = build();
    await vi.waitFor(() => expect(selectCanUseRehearsal(copilot())).toBe(true));
    await switchToRehearsal();
    release();
    await live;
    expect(calls.filter((c) => c.path === "/build").map((c) => c.body)).toEqual([
      { loop: true, cached: false },
      { loop: true, cached: true },
    ]);
    expect(copilot().step?.cached).toBe(true);
    expect(copilot().step?.log[0].text).toMatch(/rehearsal's result/);
    expect(copilot().proposal?.number).toBe(3);
    expect(selectCanUseRehearsal(copilot())).toBe(false);
  });

  it("is not offered without a recording of the running step", async () => {
    editor().open("demo", example());
    backend({ "GET /guidelines": json({ text: "" }), "GET /spec": json(emptySpec) });
    await loadWorkspace("demo");
    expect(copilot().recordings).toEqual([]);
    useCopilotStore.setState({ step: { kind: "build", running: true, log: [], error: null, progress: null, cached: false } });
    expect(selectCanUseRehearsal(copilot())).toBe(false);
  });
});

describe("build, accept and reject", () => {
  beforeEach(async () => {
    editor().open("demo", example());
    backend({ "GET /guidelines": json({ text: "" }), "GET /spec": json(emptySpec) });
    await loadWorkspace("demo");
  });
  afterEach(() => vi.unstubAllGlobals());

  async function built(extra: Record<string, () => Response> = {}) {
    const events = [
      { event: "part", part: "build", status: "running", agent: example() },
      { event: "operation", index: 0, operation: { op: "update_node", name: "greeting" }, agent: proposed() },
      { event: "done", proposal: proposal() },
    ];
    const calls = backend({
      "POST /build": streamed(sse(events)),
      "GET /spec": json(emptySpec),
      "GET /proposals/last": json(proposal()),
      ...extra,
    });
    await build();
    return calls;
  }

  it("shows the built agent on the canvas, then the proposal", async () => {
    await built();
    expect(copilot().canvas?.mode).toBe("proposal");
    expect(copilot().canvas?.agent.nodes.map((n) => n.name)).toContain("wrap_up");
    expect(copilot().proposal?.number).toBe(3);
    expect(copilot().step?.log.map((l) => l.text)).toEqual([
      "Build: customizing the template",
      "Operation 1: update node greeting",
      "Done.",
    ]);
  });

  it("accepts as one undo step, saved", async () => {
    const before = editor().agent;
    const calls = await built({
      "POST /proposals/3/accept": json({ version: { number: 7 } }),
      "GET /proposals/last": json({ ...proposal(), decision: { status: "accepted", at: "", version: 7 } }),
    });
    await accept(false);
    expect(calls.find((c) => c.path === "/proposals/3/accept")?.body).toEqual({ anyway: false });
    expect(editor().agent?.nodes.map((n) => n.name)).toContain("wrap_up");
    expect(selectIsDirty(editor())).toBe(false);
    expect(copilot().canvas).toBeNull();
    expect(copilot().notice?.text).toMatch(/version 7/);
    undo();
    expect(editor().agent).toEqual(before);
  });

  it("refuses a proposal when the draft changed after the build started", async () => {
    const calls = await built();
    editor().updateAgent({ name: "Edited after the build" });
    expect(acceptRefusal()).toMatch(/changed after this build started/);
    await accept(false);
    expect(calls.some((c) => c.path.endsWith("/accept"))).toBe(false);
    expect(copilot().notice?.tone).toBe("error");
  });

  it("rejects without touching the draft", async () => {
    const before = editor().agent;
    const calls = await built({ "POST /proposals/3/reject": json({ decision: { status: "rejected" } }) });
    await reject();
    expect(calls.some((c) => c.method === "POST" && c.path === "/proposals/3/reject")).toBe(true);
    expect(editor().agent).toBe(before);
    expect(copilot().canvas).toBeNull();
  });

  it("goes back to the draft when the build is stopped", async () => {
    let release = () => {};
    const hold = new Promise<void>((resolve) => (release = resolve));
    const events = [
      { event: "part", part: "build", status: "running", agent: example() },
      { event: "done", proposal: proposal() },
    ];
    backend({ "POST /build": streamed(sse(events), hold) });
    const running = build();
    await vi.waitFor(() => expect(copilot().canvas?.mode).toBe("building"));
    stop();
    release();
    await running;
    expect(copilot().canvas).toBeNull();
    expect(copilot().step?.running).toBe(false);
    expect(copilot().proposal).toBeNull();
  });
});
