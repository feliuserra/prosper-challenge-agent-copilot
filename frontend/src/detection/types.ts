// What GET /composer/detection returns (backend/detect/api.py, #58): the ranked
// issues and every node's numbers per clinic and version, from the call logs.

export type SignalKey =
  | "reentry"
  | "stall"
  | "hang_up"
  | "transfer"
  | "error"
  | "tool_error"
  | "duplicate"
  | "callback"
  | "quick_change";

export type Compare = "version" | "fleet";

/** A baseline's numbers, with a raw one-sided p-value and whether the detector flagged it. */
export interface BaselineNumbers {
  k: number;
  n: number;
  rate: number;
  p: number;
  flagged: boolean;
}

/** One signal at one node: `k` events out of `n` calls. */
export interface SignalNumbers {
  k: number;
  n: number;
  rate: number;
  version?: BaselineNumbers;
  fleet?: BaselineNumbers;
}

export interface NodeNumbers {
  /** Calls that entered the node. */
  entered: number;
  /** Transitions out of the node, by edge function. */
  exits: Record<string, number>;
  signals: Partial<Record<SignalKey, SignalNumbers>>;
}

export interface Evidence {
  signal: SignalKey;
  label: string;
  baseline: Compare;
  against: number | string;
  rate: number;
  base_rate: number;
  k: number;
  n: number;
  p: number;
  extra_per_week: number;
}

export interface Issue {
  /** #58's signals; a judge group with the same clinic, node and shape joins as `judge` (#32). */
  source?: "signals";
  judge?: JudgeGroup;
  id: string;
  clinic: string;
  node: string;
  shape: string;
  severity: "high" | "medium" | "low";
  version: number;
  signal: SignalKey;
  label: string;
  rate: number;
  base_rate: number;
  baseline: Compare;
  extra_per_week: number;
  score: number;
  since_week: string;
  since_version: number;
  trend: { week: string; versions: number[]; k: number; n: number; rate: number }[];
  direction: "new" | "rising" | "falling" | "steady";
  evidence: Evidence[];
  examples: string[];
}

/** A call summary (backend/detect/summary.py). */
export interface CallSummary {
  id: string;
  clinic: string;
  version: number;
  start: string;
  end: string;
  caller: string;
  /** One [node, turns, via] per visit; `via` is absent for the first node. */
  path: [string, number, string?][];
  tools: [string, string, boolean][];
  ended: "completed" | "hang_up" | "transfer" | "error";
}

/** One judged call's issue in a group (backend/detect/judge.py, #32). */
export interface JudgedCall {
  call: string;
  index: number;
  version: number | null;
  start: string | null;
  kind: string;
  label: string;
  severity: "high" | "medium" | "low";
  requirement: string;
  /** The decisive turn: its node is the group's. */
  turn: number;
  quote_turn: number;
  quote: string;
  summary: string;
  /** Whether the second, sampled run put the decisive turn in the same place. */
  agreed: boolean;
  second_turn: number | null;
}

/** The judge's issues at one clinic, node and shape, ranked like #58's. */
export interface JudgeGroup {
  source: "judge";
  id: string;
  clinic: string;
  node: string;
  shape: string;
  /** The workspace whose calls were judged (the agent's id). */
  workspace: string;
  severity: "high" | "medium" | "low";
  version: number;
  kinds: { kind: string; label: string; calls: number }[];
  label: string;
  /** Judged calls with the issue, of `judged`. */
  affected: number;
  judged: number;
  rate: number;
  /** The clinic's calls a week the rate is scaled to. */
  volume: number;
  extra_per_week: number;
  score: number;
  calls: JudgedCall[];
}

/** A judge group with no #58 issue at its clinic, node and shape: an issue of its own. */
export type JudgeIssue = JudgeGroup & { judge: JudgeGroup };

export type InboxIssue = Issue | JudgeIssue;

export const isJudgeIssue = (issue: InboxIssue): issue is JudgeIssue => issue.source === "judge";

export interface Detection {
  available: true;
  /** The week the issues are for (its Monday). */
  week: string;
  end: string;
  calls: number;
  clinics: { id: string; versions: { version: number; from: string; to: string; calls: number }[] }[];
  /** #58's issues and the judge's (#32), most urgent first. */
  issues: InboxIssue[];
  /** Judged calls per workspace. */
  judged?: Record<string, number>;
  example_calls: Record<string, CallSummary>;
  /** clinic -> version -> node -> numbers. */
  nodes: Record<string, Record<string, Record<string, NodeNumbers>>>;
  settings: {
    window_weeks: number;
    alpha: number;
    allowance: Record<Compare, number>;
    min_relative: Record<Compare, number>;
    min_absolute: number;
    min_events: number;
    stall_turns: number;
  };
  signals: Record<SignalKey, { label: string; shape: string }>;
}

export type DetectionResponse = Detection | { available: false; reason: string };

// ---- judged calls (GET /composer/calls, #32) ------------------------------------------

export interface JudgedCallRow {
  call: string;
  start: string | null;
  version: number | null;
  end_reason: string | null;
  /** "flagged: transfer, stall" or "sampled". */
  why: string;
  issues: number;
  labels: string[];
  severity: "high" | "medium" | "low" | null;
}

export interface CallIssue {
  kind: string;
  label: string;
  /** Other checklist kinds the judge gave the same problem. */
  also?: string[];
  requirement: string;
  severity: "high" | "medium" | "low";
  shape: string;
  turn: number;
  node: string;
  quote_turn: number;
  quote_node: string;
  quote: string;
  summary: string;
  agreed: boolean;
  second_turn: number | null;
}

export interface CallerCard {
  persona: string;
  goal: string;
  facts: Record<string, string>;
  style: string;
  answers: { question: string; answer: string }[];
}

export interface RecordedTurn {
  turn: number;
  speaker: "agent" | "caller";
  text: string;
  node?: string;
  calls?: { name: string; kind: string; args?: Record<string, unknown>; result?: unknown; to?: string }[];
}

export interface Ticket {
  id: string;
  received: string;
  from: string;
  text: string;
}

export interface CallDetail {
  workspace: string;
  call: {
    id: string;
    source: string;
    version: number | null;
    start: string | null;
    end: string | null;
    end_reason: string | null;
    start_node: string;
    agent: string | null;
    clinic: string;
    turns: RecordedTurn[];
  };
  path: [string, number, string?][];
  judge: {
    why: string;
    judged: string;
    issues: CallIssue[];
    other: CallIssue[];
    card: CallerCard | null;
    cost: number | null;
  } | null;
  tickets: Ticket[];
}
