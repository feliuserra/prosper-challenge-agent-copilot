import { create } from "zustand";

import type { Agent } from "../agent/schema";
import { selectIsDirty, useAgentStore } from "../store/agentStore";
import {
  acceptProposal,
  approveTests,
  deleteTest,
  getGuidelines,
  getLastProposal,
  getLastRun,
  getSpec,
  HttpError,
  putGuidelines,
  rejectProposal,
  streamBuild,
  streamSpec,
  streamTests,
  type Proposal,
  type Spec,
  type StepEvent,
  type TestRun,
} from "./api";
import { positioned } from "./diff";

// The Copilot panel's state (#31): the open agent's workspace (guidelines, spec, the
// newest proposal and test run), the step running or last run with its progress, and
// what the canvas shows instead of the draft: the agent while it is built, or a
// proposal under review. The panel is rebuilt from the workspace on load; there is no
// chat history. Accepting a proposal is one store operation, so one Cmd+Z undoes it.

export type StepKind = "spec" | "build" | "tests";

export interface LogLine {
  text: string;
  tone?: "error" | "muted";
}

export interface Step {
  kind: StepKind;
  running: boolean;
  log: LogLine[];
  error: { message: string; problems: string[] } | null;
  /** Tests ended out of all, during a test run. */
  progress: { done: number; total: number } | null;
}

/** What the canvas shows instead of the draft, read-only. */
export interface CanvasOverride {
  agent: Agent;
  mode: "building" | "proposal";
}

interface CopilotState {
  workspace: string | null;
  loading: boolean;
  loadError: string | null;
  guidelines: string;
  savedGuidelines: string;
  spec: Spec | null;
  proposal: Proposal | null;
  run: TestRun | null;
  step: Step | null;
  canvas: CanvasOverride | null;
  /** The draft (as JSON) when the build of `proposal` started in this session: Accept checks it is unchanged. */
  startedFrom: { proposal: number | null; json: string } | null;
  /** The outcome of the last decision or a refusal, shown in the proposal card. */
  notice: { text: string; tone: "ok" | "error" } | null;
}

const initial = {
  workspace: null,
  loading: false,
  loadError: null,
  guidelines: "",
  savedGuidelines: "",
  spec: null,
  proposal: null,
  run: null,
  step: null,
  canvas: null,
  startedFrom: null,
  notice: null,
} satisfies CopilotState;

export const useCopilotStore = create<CopilotState>()(() => initial);

const get = () => useCopilotStore.getState();
const set = (patch: Partial<CopilotState>) => useCopilotStore.setState(patch);
const editor = () => useAgentStore.getState();

let controller: AbortController | null = null;

/** Whether the proposal still waits for a person's decision. */
export const isPending = (proposal: Proposal | null): proposal is Proposal => proposal !== null && !proposal.decision;

/** The canvas and the side panel are read-only while the Copilot builds or a proposal is shown. */
export const selectLocked = (s: CopilotState) => s.canvas !== null;
export const selectBusy = (s: CopilotState) => s.step?.running === true;

// ---- loading ------------------------------------------------------------------------------------
/** Open the workspace of agent `id` (the workspace has the agent's id, ADR 0013). */
export async function loadWorkspace(id: string | null) {
  controller?.abort();
  useCopilotStore.setState({ ...initial, workspace: id, loading: id !== null });
  if (!id) return;
  try {
    const [guidelines, spec, proposal, run] = await Promise.all([
      getGuidelines(id),
      getSpec(id),
      getLastProposal(id),
      getLastRun(id),
    ]);
    if (get().workspace !== id) return;
    set({ loading: false, guidelines, savedGuidelines: guidelines, spec, proposal, run });
  } catch (error) {
    if (get().workspace === id) set({ loading: false, loadError: String(error) });
  }
}

export function setGuidelines(guidelines: string) {
  set({ guidelines });
}

async function refresh() {
  const id = get().workspace;
  if (!id) return;
  const [spec, proposal, run] = await Promise.all([getSpec(id), getLastProposal(id), getLastRun(id)]);
  if (get().workspace === id) set({ spec, proposal, run });
}

// ---- steps --------------------------------------------------------------------------------------
/**
 * Run a step's stream: each event goes to `onEvent` and to the log. Returns the last
 * event, or the error that stopped the step before it started (an HttpError).
 */
async function runStep(
  kind: StepKind,
  open: (signal: AbortSignal) => AsyncGenerator<StepEvent>,
  onEvent: (event: StepEvent) => void,
): Promise<StepEvent | Error | null> {
  controller?.abort();
  const mine = new AbortController();
  controller = mine;
  const workspace = get().workspace;
  set({ step: { kind, running: true, log: [], error: null, progress: null }, notice: null });
  const update = (change: (step: Step) => Partial<Step>) => {
    const step = get().step;
    if (step && controller === mine && get().workspace === workspace) set({ step: { ...step, ...change(step) } });
  };
  let last: StepEvent | null = null;
  try {
    for await (const event of open(mine.signal)) {
      // Stopped: nothing more from this stream counts, even if it is still delivered.
      if (controller !== mine || mine.signal.aborted) break;
      last = event;
      const line = describe(event);
      update((step) => ({
        log: line ? [...step.log, line] : step.log,
        error: event.event === "error" ? { message: event.message, problems: event.problems } : step.error,
        progress: event.event === "test" ? { done: event.done, total: event.total } : step.progress,
      }));
      onEvent(event);
    }
    if (mine.signal.aborted) throw new DOMException("Stopped", "AbortError");
    if (controller === mine && last?.event !== "done" && last?.event !== "error") {
      update(() => ({
        error: { message: "The connection to the backend ended before the step finished.", problems: [] },
      }));
    }
    return last;
  } catch (error) {
    if (mine.signal.aborted) {
      update((step) => ({ log: [...step.log, { text: "Stopped.", tone: "muted" }] }));
      return null;
    }
    update(() => ({ error: { message: error instanceof Error ? error.message : String(error), problems: [] } }));
    return error instanceof Error ? error : new Error(String(error));
  } finally {
    if (controller === mine) {
      update(() => ({ running: false }));
      controller = null;
    }
  }
}

/** Stop the running step: the request is aborted, and the backend drops the step. */
export function stop() {
  controller?.abort();
  if (get().canvas?.mode === "building") set({ canvas: null, startedFrom: null });
}

/** Save the guidelines and run the spec step on them. Approved tests are replaced only after a confirm. */
export async function createFromGuidelines(replaceApproved = false) {
  const { workspace, guidelines } = get();
  if (!workspace) return;
  try {
    await putGuidelines(workspace, guidelines);
    set({ savedGuidelines: guidelines });
  } catch (error) {
    set({
      step: { kind: "spec", running: false, log: [], error: { message: String(error), problems: [] }, progress: null },
    });
    return;
  }
  const result = await runStep(
    "spec",
    (signal) => streamSpec(workspace, replaceApproved, signal),
    (event) => {
      if (event.event === "done" && event.spec) set({ spec: event.spec });
    },
  );
  if (result instanceof HttpError && result.status === 409 && !replaceApproved && /approved/i.test(result.message)) {
    if (confirm(`${result.message}\n\nReplace them with new draft tests?`)) await createFromGuidelines(true);
  }
}

/** Build the agent from the approved spec (with the test loop, unless `loop` is false). */
export async function build(loop = true) {
  const { workspace } = get();
  const draft = editor().agent;
  if (!workspace || !draft) return;
  // Nothing hidden under the built agent stays selected (Backspace would delete it).
  editor().select(null);
  set({ startedFrom: { proposal: null, json: JSON.stringify(draft) } });
  const result = await runStep(
    "build",
    (signal) => streamBuild(workspace, loop, signal),
    (event) => {
      const shown = get().canvas?.agent ?? draft;
      if (event.event === "part" && event.part === "build" && event.status === "running" && event.agent) {
        set({ canvas: { agent: positioned(event.agent as Agent, draft), mode: "building" } });
      } else if (event.event === "operation") {
        set({ canvas: { agent: positioned(event.agent, shown), mode: "building" } });
      } else if (event.event === "done" && event.proposal) {
        const proposal = event.proposal;
        set({
          proposal,
          canvas: { agent: positioned(proposal.agent, shown), mode: "proposal" },
          startedFrom: { proposal: proposal.number, json: get().startedFrom?.json ?? JSON.stringify(draft) },
        });
      }
    },
  );
  // Stopped, failed or refused: back to the draft.
  if (!(result && !(result instanceof Error) && result.event === "done")) {
    if (get().canvas?.mode === "building") set({ canvas: null });
    set({ startedFrom: null });
  }
  if (result && !(result instanceof Error) && result.event === "done") await refresh().catch(() => {});
}

/** Run the approved tests on the agent as it is in the editor. */
export async function runTests() {
  const { workspace } = get();
  const agent = editor().agent;
  if (!workspace || !agent) return;
  await runStep(
    "tests",
    (signal) => streamTests(workspace, agent, signal),
    (event) => {
      if (event.event === "done" && event.run) set({ run: event.run });
    },
  );
}

// ---- tests --------------------------------------------------------------------------------------
async function specChange(change: (workspace: string) => Promise<Spec>) {
  const { workspace } = get();
  if (!workspace) return;
  try {
    const spec = await change(workspace);
    if (get().workspace === workspace) set({ spec, notice: null });
  } catch (error) {
    set({ notice: { text: error instanceof Error ? error.message : String(error), tone: "error" } });
  }
}

export const approve = (testId?: string) => specChange((ws) => approveTests(ws, testId));
export const removeTest = (testId: string) => specChange((ws) => deleteTest(ws, testId));

// ---- the proposal -------------------------------------------------------------------------------
/** Show the pending proposal on the canvas, or the draft again. */
export function showProposal(show: boolean) {
  const { proposal } = get();
  if (show && isPending(proposal)) {
    editor().select(null);
    set({ canvas: { agent: positioned(proposal.agent, editor().agent), mode: "proposal" } });
  } else if (!show && get().canvas?.mode === "proposal") {
    set({ canvas: null });
  }
}

/** Why the draft cannot take the proposal, or null when it can. */
export function acceptRefusal(): string | null {
  const { proposal, startedFrom } = get();
  const state = editor();
  if (!state.agent || !proposal) return "Nothing to accept.";
  if (startedFrom?.proposal === proposal.number) {
    if (JSON.stringify(state.agent) !== startedFrom.json) {
      return "The draft changed after this build started, so the proposal does not include those changes. Undo them, or build again.";
    }
  } else if (selectIsDirty(state)) {
    return "The draft has unsaved changes this proposal did not see. Undo them, or build again.";
  }
  return null;
}

/**
 * Accept the proposal: the backend writes the agent (a new version, source copilot),
 * its clinic and configuration, then the draft takes it in one undo step. `anyway` for
 * a proposal blocked by its tests.
 */
export async function accept(anyway = false) {
  const { workspace, proposal } = get();
  const refusal = acceptRefusal();
  if (!workspace || !proposal || refusal) {
    set({ notice: { text: refusal ?? "Nothing to accept.", tone: "error" } });
    return;
  }
  try {
    const version = await acceptProposal(workspace, proposal.number, anyway);
    const draft = editor().agent;
    editor().replaceAgent(get().canvas?.agent ?? positioned(proposal.agent, draft));
    editor().markSaved();
    set({
      canvas: null,
      startedFrom: null,
      notice: {
        text: `Accepted and saved as version ${version.number}. Undo (Cmd+Z) brings the old draft back.`,
        tone: "ok",
      },
    });
    await refresh();
  } catch (error) {
    set({ notice: { text: error instanceof Error ? error.message : String(error), tone: "error" } });
  }
}

/** Reject the proposal: the draft and the workspace stay as they are; the decision is recorded. */
export async function reject() {
  const { workspace, proposal } = get();
  if (!workspace || !proposal) return;
  try {
    await rejectProposal(workspace, proposal.number);
    set({ canvas: null, startedFrom: null, notice: { text: "Rejected. The draft is unchanged.", tone: "ok" } });
    await refresh();
  } catch (error) {
    set({ notice: { text: error instanceof Error ? error.message : String(error), tone: "error" } });
  }
}

// ---- progress lines -----------------------------------------------------------------------------
const PARTS: Record<string, string> = {
  requirements: "Requirements",
  configuration: "Clinic configuration",
  tests: "Tests",
  build: "Build",
  diagnosis: "Diagnosis",
};

const partName = (part: string) => PARTS[part] ?? part.charAt(0).toUpperCase() + part.slice(1);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const count = (value: unknown) => (Array.isArray(value) ? value.length : 0);

/** One line of the step's log for an event, or null for events the log leaves out. */
export function describe(event: StepEvent): LogLine | null {
  switch (event.event) {
    case "part": {
      const name = partName(event.part);
      if (event.status === "running") {
        if (event.part === "build") return { text: "Build: customizing the template" };
        if (event.part === "tests" && typeof event.total === "number")
          return { text: `Running ${plural(event.total, "test")}` };
        return { text: `${name}: working…` };
      }
      if (event.status === "planned") return { text: `${name}: ${plural(count(event.plan), "test")} planned` };
      if (event.status === "done") {
        if (event.part === "requirements") {
          return {
            text: `${name}: ${plural(count(event.requirements), "requirement")}, ${plural(count(event.questions), "client question")}`,
          };
        }
        if (event.part === "tests") return { text: `${name}: ${plural(count(event.tests), "test")} written` };
        if (event.part === "build")
          return {
            text: `Build: done, ${plural(count(event.uncarried), "requirement")} left to the template or tools`,
          };
        return { text: `${name}: done` };
      }
      return null;
    }
    case "repair":
      return {
        text: `${partName(event.part)}: ${plural(event.problems.length, "problem")} sent back to the model (try ${event.attempt + 1})`,
        tone: "muted",
      };
    case "operation": {
      const op = event.operation;
      const target = typeof op.name === "string" ? op.name : typeof op.source === "string" ? op.source : "";
      return { text: `Operation ${event.index + 1}: ${op.op.replace(/_/g, " ")}${target ? ` ${target}` : ""}` };
    }
    case "tests":
      return { text: `Tests (${event.label}): ${event.results.passing}/${event.results.total} passing` };
    case "round":
      return {
        text: `Round ${event.round}: ${event.kept ? "change kept" : "change not kept"}${event.reason ? `. ${event.reason}` : ""}${event.error ? `. ${event.error}` : ""}`,
      };
    case "test":
      return {
        text: `${event.result.test_id}: ${event.result.status}`,
        tone: event.result.status === "pass" ? "muted" : undefined,
      };
    case "done":
      return { text: "Done." };
    case "error":
      return { text: event.message, tone: "error" };
  }
}
