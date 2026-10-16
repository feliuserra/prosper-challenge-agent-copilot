import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Agent } from "../agent/schema";
import { useSideStore } from "../components/sideStore";
import { useAgentStore } from "../store/agentStore";
import { toolCalls, turnMarks } from "./calls";
import { useCallsStore } from "./callsStore";
import { useDetectionStore } from "./detectionStore";
import { issuesAt } from "./heat";
import type { CallDetail, CallIssue, Detection, Issue, JudgeIssue } from "./types";

const agent = JSON.parse(
  readFileSync(new URL("../../../backend/tests/fixtures/linear-agent.json", import.meta.url), "utf8"),
) as Agent;

function callIssue(patch: Partial<CallIssue>): CallIssue {
  return {
    kind: "wrong_patient", label: "wrong patient or name", requirement: "", severity: "high", shape: "silent",
    turn: 4, node: agent.nodes[1].name, quote_turn: 7, quote_node: agent.nodes[1].name, quote: "Is that Sara Boreal?",
    summary: "Never spelled.", agreed: true, second_turn: 4, ...patch,
  };
}

const detail: CallDetail = {
  workspace: "linden-grove",
  call: {
    id: "lg-1019-0804", source: "production-mock", version: 1, start: "2026-10-19T08:04:00", end: "2026-10-19T08:06:57",
    end_reason: "end_node", start_node: "greeting", agent: "Linden Grove scheduler", clinic: "linden-grove",
    turns: [
      { turn: 4, speaker: "agent", text: "Your name?", node: "ask_name" },
      { turn: 5, speaker: "caller", text: "Sara Boreal." },
      { turn: 7, speaker: "agent", text: "Is that Sara Boreal?", node: "confirm_name" },
    ],
  },
  path: [["greeting", 1], ["ask_name", 1, "choose_intent"]],
  judge: {
    why: "flagged: stall", judged: "", other: [], card: null, cost: 0.01,
    issues: [callIssue({}), callIssue({ kind: "requirement", requirement: "R35", turn: 7, quote_turn: 7, node: "not_in_the_agent" })],
  },
  tickets: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
  useCallsStore.setState({ open: null, detail: { state: "idle" } });
});

describe("the Calls tab's helpers", () => {
  it("mark each issue at its quoted turn and at its decisive turn", () => {
    const marks = turnMarks(detail.judge!.issues);
    expect(marks.get(7)).toEqual({ quoted: [0, 1], decisive: [1] });
    expect(marks.get(4)).toEqual({ quoted: [], decisive: [0] });
    expect(marks.has(5)).toBe(false);
  });

  it("render tool calls with their arguments and mark refusals", () => {
    const turn = {
      turn: 12, speaker: "agent" as const, text: "", node: "verify_patient",
      calls: [
        { kind: "tool", name: "lookup_patient", args: { full_name: "Sara Boreal", date_of_birth: "1984-03-03" }, result: { found: false } },
        { kind: "tool", name: "find_slots", args: { time_of_day: "evening" }, result: { error: "no" } },
        { kind: "edge", name: "patient_identified", to: "collect_reason" },
      ],
    };
    expect(toolCalls(turn)).toEqual([
      { text: "lookup_patient(full_name: Sara Boreal, date_of_birth: 1984-03-03)", failed: false },
      { text: "find_slots(time_of_day: evening)", failed: true },
    ]);
  });
});

describe("judge issues in the inbox", () => {
  const signals = { id: "a:x:leak", source: "signals", clinic: "a", version: 1, node: "x" } as Issue;
  const judged = { id: "a:x:silent", source: "judge", clinic: "a", version: 1, node: "x" } as JudgeIssue;
  const detection = { issues: [judged, signals] } as unknown as Detection;

  it("do not tint the heatmap: their versions are the workspace's", () => {
    expect(issuesAt(detection, { clinic: "a", version: "1", compare: "fleet", signal: "issues" }, "x")).toEqual([signals]);
  });

  it("select their node without changing the heatmap's view", () => {
    useAgentStore.getState().open("example", agent);
    useDetectionStore.setState({ options: { clinic: "z", version: "3", compare: "fleet", signal: "hang_up" } });
    useDetectionStore.getState().focusIssue({ ...judged, node: agent.nodes[2].name });
    expect(useDetectionStore.getState().focus).toBe("a:x:silent");
    expect(useDetectionStore.getState().options?.clinic).toBe("z");
    expect(useAgentStore.getState().selection).toEqual({ kind: "node", name: agent.nodes[2].name });
  });
});

describe("opening a judged call", () => {
  it("opens the Calls tab at the issue's quote and selects its decisive node", async () => {
    const fetch = vi.fn(async (_url: string) => new Response(JSON.stringify(detail)));
    vi.stubGlobal("fetch", fetch);
    useAgentStore.getState().open("example", agent);
    useSideStore.setState({ tab: "copilot" });
    await useCallsStore.getState().openCall("linden-grove", "lg-1019-0804", 0);
    expect(fetch.mock.calls[0][0]).toBe("/composer/calls/linden-grove/lg-1019-0804");
    expect(useSideStore.getState().tab).toBe("calls");
    expect(useCallsStore.getState().open).toMatchObject({ call: "lg-1019-0804", issue: 0, turn: 7 });
    expect(useAgentStore.getState().selection).toEqual({ kind: "node", name: agent.nodes[1].name });
    // An issue whose node the open agent lacks changes no selection.
    useCallsStore.getState().focus(1);
    expect(useCallsStore.getState().open).toMatchObject({ issue: 1, turn: 7 });
    expect(useAgentStore.getState().selection).toEqual({ kind: "node", name: agent.nodes[1].name });
  });

  it("keeps only the latest call when two are opened in a row", async () => {
    let answer: (r: Response) => void = () => {};
    vi.stubGlobal("fetch", vi.fn().mockImplementationOnce(() => new Promise<Response>((r) => (answer = r))).mockImplementationOnce(
      async () => new Response(JSON.stringify({ ...detail, call: { ...detail.call, id: "second" } })),
    ));
    const first = useCallsStore.getState().openCall("linden-grove", "first");
    await useCallsStore.getState().openCall("linden-grove", "second");
    answer(new Response(JSON.stringify(detail)));
    await first;
    const state = useCallsStore.getState();
    expect(state.open?.call).toBe("second");
    expect(state.detail.state === "ready" && state.detail.data.call.id).toBe("second");
  });
});
