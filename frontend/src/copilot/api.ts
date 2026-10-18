import type { Agent } from "../agent/schema";

// Client for the Copilot's workspace API (backend/copilot/api.py), reached through the
// Vite proxy. The steps (spec, build, fix, test run) answer with a stream of server-sent
// events over a POST, so they are read from fetch's body rather than an EventSource.

export interface Requirement {
  id: string;
  text: string;
  /** Quotes from the guidelines; empty for the baseline rules every agent has. */
  sources: string[];
  baseline: boolean;
  /** The client question this requirement is the default answer to. */
  question: string | null;
}

export interface ClientQuestion {
  id: string;
  question: string;
  default: string;
}

export interface SpecTest {
  id: string;
  title: string;
  tier: string;
  requirements: string[];
  status: "draft" | "approved";
}

export interface Spec {
  requirements: Requirement[];
  set_aside: { source: string; reason: string }[];
  questions: ClientQuestion[];
  /** A clinic file (#43), or null before the spec step. */
  configuration: unknown;
  tests: SpecTest[];
  gaps?: { uncarried: string[]; untested: string[] };
}

export interface FailedCheck {
  type: string;
  tool: string | null;
  rule: string | null;
  detail: string | null;
  turn: number | null;
}

export interface TestRow {
  test_id: string;
  tier: string;
  status: "pass" | "flaky" | "fail" | "error";
  cached: boolean;
  failed: FailedCheck[];
}

export interface TestSummary {
  tests: TestRow[];
  counts: Record<string, number>;
  passing: number;
  total: number;
}

export interface Diagnosis {
  test: string;
  link: string | null;
  turn: number | null;
  explanation: string;
  question: string | null;
}

export interface Round {
  round: number;
  kept: boolean;
  reason?: string;
  error?: string;
  rationale?: string;
  diagnoses?: Diagnosis[];
  operations?: unknown[];
  rerun?: TestSummary;
  full?: TestSummary;
}

/** K continuations of a call from its start (#33): the reproduction on one agent. */
export interface Rollout {
  k: number;
  passed: number;
  failed: number;
  rate: string;
}

export interface FixCandidate {
  number: number;
  rationale: string;
  operations: { op: string }[];
  /** replay_turn on the decisive turn; null with `error` when it could not run. */
  turn: { passed: number | null; rate: string | null; error?: string | null };
  /** The full reproduction on the candidate, for the agreement number. */
  full?: Rollout;
}

/** The issue a fix proposal fixes (#33). */
export interface FixIssue {
  call: string;
  turn: number;
  kind: string;
  label: string | null;
  requirement: string;
  summary: string;
  node: string;
}

export interface Proposal {
  number: number;
  created: string;
  status: "ready" | "blocked";
  blocked: string[];
  started_from: { template?: string; hash: string; agent?: string | null };
  /** "fix" for a fix from an issue (#33); a build's proposal has none. */
  kind?: "fix";
  configuration: unknown;
  /** A build's; a fix leaves the configuration alone. */
  configuration_entries?: number;
  configuration_changes: { key: string }[];
  outline?: string[];
  issue?: FixIssue;
  reproduction?: { test: { id: string; title: string }; before: Rollout; after?: Rollout; corrections: { said: string; heard: string; ticket: string }[] };
  turn_before?: { passed: number | null; rate: string | null };
  diagnosis?: { link: string; turn: number | null; explanation: string; question: string | null };
  candidates?: FixCandidate[];
  chosen?: number;
  agreement?: { k: number; agreed: number; of: number; best_turn_is_best_full: boolean };
  regressions?: string[];
  /** A fix's tests that failed on the current agent, so were not run again after it. */
  not_rerun?: string[];
  operations: { op: string }[];
  agent: Agent;
  uncarried?: { requirement: string; reason: string }[];
  diagnoses: Diagnosis[];
  questions: { test: string; question: string }[];
  concerns: unknown[];
  rounds: Round[];
  results: { before: TestSummary; after: TestSummary } | null;
  leaks: string[];
  meta: { seconds: number; cost: { copilot: number | null; tests: number | null } };
  decision?: { status: "accepted" | "rejected"; at: string; version?: number; blocked?: boolean };
}

/** What a fix did (#33), stored whether or not it got to a proposal. */
export interface FixReport {
  number?: number;
  created: string;
  issue: FixIssue;
  outcome: "proposal" | "not_reproduced" | "no_candidate";
  message: string;
  proposal?: number;
}

export interface TestRun {
  number?: number;
  created: string;
  agent_hash: string | null;
  proposal: number | null;
  summary: TestSummary | null;
  cost: number | null;
}

/** An event of a step's stream; see backend/copilot/api.py for each type. */
export type StepEvent =
  | { event: "part"; part: string; status: string; [key: string]: unknown }
  | { event: "repair"; part: string; attempt: number; problems: string[] }
  | { event: "operation"; index: number; operation: { op: string; [key: string]: unknown }; agent: Agent }
  | { event: "tests"; label: string; results: TestSummary }
  | ({ event: "round" } & Round)
  | { event: "test"; done: number; total: number; result: TestRow }
  | ({ event: "backcast" } & Rollout)
  | ({ event: "candidate"; number: number } & Partial<Pick<FixCandidate, "rationale" | "turn" | "full">>)
  | { event: "done"; spec?: Spec; proposal?: Proposal; run?: TestRun; fix?: FixReport }
  | { event: "error"; part: string | null; message: string; problems: string[] };

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const base = (workspace: string) => `/copilot/workspaces/${encodeURIComponent(workspace)}`;

async function call(workspace: string, path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(base(workspace) + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) throw new HttpError(res.status, await errorText(res));
  return res;
}

/** FastAPI's `detail`, or the body as it is. */
async function errorText(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const detail = JSON.parse(text).detail;
    if (typeof detail === "string") return detail;
  } catch {
    // not JSON
  }
  return text || `${res.status} ${res.statusText}`;
}

/** `fetch` for something that may not exist yet: null on 404. */
async function maybe<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) return null;
    throw error;
  }
}

export async function getGuidelines(workspace: string): Promise<string> {
  return (await (await call(workspace, "/guidelines")).json()).text;
}

export async function putGuidelines(workspace: string, text: string): Promise<void> {
  await call(workspace, "/guidelines", { method: "PUT", body: JSON.stringify({ text }) });
}

export async function getSpec(workspace: string): Promise<Spec> {
  return (await call(workspace, "/spec")).json();
}

export const getLastProposal = (workspace: string) =>
  maybe<Proposal>(async () => (await call(workspace, "/proposals/last")).json());

export const getLastRun = (workspace: string) =>
  maybe<TestRun>(async () => (await call(workspace, "/runs/last")).json());

/** Approve one draft test, or all of them. Returns the spec after the change. */
export async function approveTests(workspace: string, testId?: string): Promise<Spec> {
  const path = testId ? `/spec/tests/${encodeURIComponent(testId)}` : "/spec/tests";
  const res = await call(workspace, path, { method: "PATCH", body: JSON.stringify({ status: "approved" }) });
  return (await res.json()).spec;
}

export async function deleteTest(workspace: string, testId: string): Promise<Spec> {
  return (await (await call(workspace, `/spec/tests/${encodeURIComponent(testId)}`, { method: "DELETE" })).json()).spec;
}

export async function acceptProposal(workspace: string, number: number, anyway: boolean): Promise<{ number: number }> {
  const res = await call(workspace, `/proposals/${number}/accept`, {
    method: "POST",
    body: JSON.stringify({ anyway }),
  });
  return (await res.json()).version;
}

export async function rejectProposal(workspace: string, number: number): Promise<void> {
  await call(workspace, `/proposals/${number}/reject`, { method: "POST" });
}

/** The spec step's stream. Rejected with an HttpError before it starts (e.g. 409 when approved tests would go). */
export const streamSpec = (workspace: string, replaceApproved: boolean, signal: AbortSignal) =>
  stream(workspace, "/spec", { replace_approved: replaceApproved }, signal);

export const streamBuild = (workspace: string, loop: boolean, signal: AbortSignal) =>
  stream(workspace, "/build", { loop }, signal);

/** Fix the judge's issue decided at `turn` of `call`, from the saved agent (#33). */
export const streamFix = (workspace: string, call: string, turn: number, signal: AbortSignal) =>
  stream(workspace, "/fix", { call, turn }, signal);

export const getLastFix = (workspace: string) =>
  maybe<FixReport>(async () => (await call(workspace, "/fixes/last")).json());

export const streamTests = (workspace: string, agent: Agent, signal: AbortSignal) =>
  stream(workspace, "/tests/run", { agent }, signal);

async function* stream(workspace: string, path: string, body: unknown, signal: AbortSignal): AsyncGenerator<StepEvent> {
  const res = await call(workspace, path, { method: "POST", body: JSON.stringify(body), signal });
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseEvents(buffer + value);
    buffer = parsed.rest;
    yield* parsed.events;
  }
}

/**
 * The complete server-sent events in `text` (each ends with a blank line), and what is
 * left after them: a chunk can end in the middle of an event.
 */
export function parseEvents(text: string): { events: StepEvent[]; rest: string } {
  const blocks = text.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: StepEvent[] = [];
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (data) events.push(JSON.parse(data));
  }
  return { events, rest };
}
